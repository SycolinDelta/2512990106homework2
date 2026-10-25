"""Workflow 编排器（orchestrator）：驱动多个 Agent 按流程定义依次执行。

职责：
1. 按 WorkflowGraph 的定义，从入口节点开始一路执行到 END；
2. 在节点之间传递 WorkflowState（状态共享）和 Message（消息传递）；
3. 支持顺序执行、条件分支、受控循环（max_rounds 上限）；
4. 单节点出错自动重试 retry 次，重试仍失败则终止流程但不崩溃；
5. 记录执行日志：每个节点的耗时、状态快照、Agent 间消息，可写入 JSON 文件。

注意：编排器只处理内存中的 WorkflowState，不会写任何源文件。
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from workflow.graph import END, WorkflowGraph
from workflow.state import WorkflowState

# 节点执行结果的状态码
OK = "ok"
FAILED = "failed"
SKIPPED = "skipped"


class Orchestrator:
    """执行一个 WorkflowGraph。"""

    def __init__(self, graph: WorkflowGraph, retry: int = 1,
                 on_event: Optional[Callable[[str], None]] = None,
                 cancel_check: Optional[Callable[[], bool]] = None):
        """
        参数：
            graph:        要执行的流程定义
            retry:        单个节点失败后的重试次数（不含首次）
            on_event:     事件回调，用来实时打印进度（None 表示不打印）
            cancel_check: 取消检查函数，返回 True 时中止流程
        """
        self.graph = graph
        self.retry = retry
        self.on_event = on_event or (lambda _msg: None)
        self.cancel_check = cancel_check

    # ------------------------------------------------------------------
    def run(self, state: WorkflowState) -> WorkflowState:
        """从入口节点开始执行，直到 END 或出错。"""
        state.max_rounds = self.graph.max_rounds
        state.finished = False
        state.stop_reason = ""
        visited: List[str] = []
        current = self.graph.entry

        while current != END:
            # 1) 取消检查（例如用户 Ctrl+C）
            if self.cancel_check and self.cancel_check():
                state.stop_reason = "cancelled"
                state.finished = True
                state.log("cancelled", node=current)
                self.on_event("流程已被用户取消")
                break

            node = self.graph.nodes[current]
            state.log("node_start", node=current, round=state.round)
            self.on_event(f"→ 节点 {current} 开始执行（{node.description}）")
            started = time.time()

            # 1.5) 循环上限保护：审查-修复循环达到上限后，强制进入验证，防止死循环
            if current == "reviewer" and state.round >= state.max_rounds:
                state.log("loop_limit_reached", round=state.round, max_rounds=state.max_rounds)
                self.on_event(f"  ! 已达到审查-修复循环上限（{state.max_rounds} 轮），转去验证")
                current = "tester"
                continue
            # 2) 执行节点，带重试
            ok, error = self._run_node_with_retry(node.name, node.agent, state)
            elapsed = round(time.time() - started, 3)
            visited.append(current)

            if not ok:
                # 重试用完仍失败：记录错误、终止流程，但不抛出异常
                state.error = error
                state.stop_reason = error or "error"
                state.finished = True
                state.log("node_failed", node=current, error=error, elapsed=elapsed)
                self.on_event(f"✗ 节点 {current} 执行失败：{error}")
                break

            state.log("node_done", node=current, elapsed=elapsed, state=state.snapshot())
            self.on_event(f"✓ 节点 {current} 完成（耗时 {elapsed}s）")

            # 3) 按边计算下一个节点
            current = self.graph.next_node(current, state)

        # 4) 结束：没有任何异常时记为正常结束
        if not state.finished:
            state.finished = True
            state.stop_reason = state.stop_reason or "completed"
        state.log("workflow_end", visited=visited, stop_reason=state.stop_reason)
        return state

    # ------------------------------------------------------------------
    def _run_node_with_retry(self, name: str,
                             agent: Callable[[WorkflowState], None],
                             state: WorkflowState):
        """执行一个节点，失败时按 retry 次数重试。返回 (是否成功, 错误信息)。"""
        last_error = ""
        for attempt in range(self.retry + 1):
            try:
                agent(state)
                return True, ""
            except Exception as err:  # noqa: BLE001 —— 节点任何异常都不能让程序崩溃
                last_error = f"{type(err).__name__}: {err}"
                state.log("node_error", node=name, attempt=attempt, error=last_error)
                if attempt < self.retry:
                    self.on_event(f"  ! 节点 {name} 第 {attempt + 1} 次执行出错，正在重试：{last_error}")
                else:
                    self.on_event(f"  ! 节点 {name} 重试 {self.retry} 次后仍然失败")
        return False, last_error


def run_workflow(graph: WorkflowGraph, state: WorkflowState,
                 retry: int = 1,
                 on_event: Optional[Callable[[str], None]] = None,
                 cancel_check: Optional[Callable[[], bool]] = None) -> WorkflowState:
    """便捷函数：创建编排器并执行。"""
    return Orchestrator(graph, retry=retry, on_event=on_event,
                        cancel_check=cancel_check).run(state)
