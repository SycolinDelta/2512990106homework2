"""声明式流程定义（graph）。

流程用「节点 + 边 + 条件 + 循环上限」声明出来，而不是把调用顺序硬编码在代码里。
要新增一个 Agent 或改流程顺序，只需要在这里加一个节点、改一条边，编排层和 Agent 都不用动
（对应 Homework2 评审标准里的「可扩展性」）。

默认流程（代码审查流程）：

    START → coder → reviewer ──(发现问题)──→ fixer ──→ reviewer(循环，有上限)
                       │
                       └────(没发现问题)────→ tester → END

对应的 mermaid 流程图可以通过 `python main.py --graph` 打印。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from workflow.state import WorkflowState

# 终止节点的名字，走到这里表示流程结束
END = "END"
START = "START"


@dataclass
class Node:
    """一个流程节点：绑定一个 Agent（callable(state) -> None），外加可选的展示信息。"""

    name: str                          # 节点名，在图中唯一
    agent: Callable[["WorkflowState"], None]   # 处理函数：读写 WorkflowState
    description: str = ""              # 一句话说明，用于打印流程图与文档


@dataclass
class Edge:
    """一条有向边。condition 为 None 表示无条件跳转，否则按返回值选择目标。

    condition 签名：condition(state) -> str，返回 next 字典里的 key。
    """

    source: str
    targets: Dict[str, str] = field(default_factory=dict)  # key -> 目标节点名
    condition: Optional[Callable[["WorkflowState"], str]] = None


class WorkflowGraph:
    """流程定义 + 一个极简的静态检查（防止定义写了不存在的节点）。"""

    def __init__(self, name: str = "workflow"):
        self.name = name
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        self.entry: str = ""
        self.max_rounds: int = 3

    # ------------------------------------------------------------------
    # 构建 API
    # ------------------------------------------------------------------
    def add_node(self, name: str, agent: Callable[["WorkflowState"], None],
                 description: str = "") -> "WorkflowGraph":
        """注册一个节点（链式调用）。"""
        if name in self.nodes:
            raise ValueError(f"节点重复定义：{name}")
        self.nodes[name] = Node(name=name, agent=agent, description=description)
        return self

    def add_edge(self, source: str, target: str) -> "WorkflowGraph":
        """注册一条无条件边。"""
        self.edges.append(Edge(source=source, targets={"default": target}))
        return self

    def add_conditional_edge(self, source: str,
                             condition: Callable[["WorkflowState"], str],
                             targets: Dict[str, str]) -> "WorkflowGraph":
        """注册一条条件边：按 condition 的返回值挑选 targets 中的目标。"""
        self.edges.append(Edge(source=source, targets=dict(targets), condition=condition))
        return self

    def set_entry(self, name: str) -> "WorkflowGraph":
        """设置入口节点。"""
        self.entry = name
        return self

    # ------------------------------------------------------------------
    # 查询与可视化
    # ------------------------------------------------------------------
    def next_node(self, current: str, state: WorkflowState) -> str:
        """计算下一个节点：先找无条件边，再按条件边求值。"""
        for edge in self.edges:
            if edge.source != current:
                continue
            if edge.condition is None:
                return edge.targets["default"]
            key = edge.condition(state)
            if key not in edge.targets:
                raise ValueError(f"条件边返回了未定义的分支 {key!r}：{current}")
            return edge.targets[key]
        return END  # 没有出边 = 终态

    def validate(self) -> None:
        """静态检查：入口存在、边上的节点都存在。"""
        if not self.entry or self.entry not in self.nodes:
            raise ValueError(f"入口节点未定义或不存在：{self.entry!r}")
        known = set(self.nodes) | {END}
        for edge in self.edges:
            if edge.source not in self.nodes:
                raise ValueError(f"边的起点不存在：{edge.source}")
            for target in edge.targets.values():
                if target not in known:
                    raise ValueError(f"边的终点不存在：{target}")
        for name in self.nodes:
            if not any(e.source == name for e in self.edges):
                raise ValueError(f"节点 {name} 没有出边（流程无法结束或继续）")

    def to_mermaid(self) -> str:
        """把流程渲染成 mermaid 图（直接贴进 Design.md 或 markdown 查看器）。"""
        lines = ["flowchart TD", f"    START([开始]) --> {self.entry}"]
        for name, node in self.nodes.items():
            # 节点只显示名称，说明文字放在文档里，避免图上文字拥挤
            lines.append(f'    {name}["{name}"]')
        for edge in self.edges:
            if edge.condition is None:
                target = edge.targets["default"]
                lines.append(f"    {edge.source} --> {target}")
            else:
                for key, target in edge.targets.items():
                    lines.append(f"    {edge.source} -- {key} --> {target}")
        lines.append("    END([结束])")
        return "\n".join(lines)

    def describe(self) -> str:
        """打印用的文字版流程说明。"""
        out = [f"Workflow: {self.name}", f"  入口: {self.entry}", "  节点:"]
        for name, node in self.nodes.items():
            out.append(f"    - {name}: {node.description or '(无说明)'}")
        out.append("  边:")
        for edge in self.edges:
            if edge.condition is None:
                out.append(f"    {edge.source} -> {edge.targets['default']}")
            else:
                out.append(f"    {edge.source} -> ?({', '.join(edge.targets.keys())})")
        out.append(f"  循环上限: max_rounds = {self.max_rounds}")
        return "\n".join(out)


# ----------------------------------------------------------------------
# 默认流程：代码审查流程（编码 → 审查 → 修复 → 验证）
# ----------------------------------------------------------------------
def _has_issues(state: WorkflowState) -> str:
    """条件函数：审查后是否还有需要修的问题。"""
    review = state.review or {}
    return "有Bug" if review.get("has_issues") else "无Bug"


def build_default_graph(coder, reviewer, fixer, tester,
                        max_rounds: int = 3) -> WorkflowGraph:
    """组装默认的代码审查 Workflow。

    参数是四个 Agent 的 callable(state)，由调用方注入：
    这样同一套流程既能接真 LLM Agent，也能接 Mock Agent（可扩展性）。
    """
    graph = WorkflowGraph(name="code_review_workflow")
    graph.max_rounds = max_rounds   # 由编排器强制执行（达到上限后跳到 tester）
    graph.add_node("coder", coder, "接收原始代码并登记到共享状态")
    graph.add_node("reviewer", reviewer, "审查代码，找出必须修复的Bug")
    graph.add_node("fixer", fixer, "按审查结论自动修复代码")
    graph.add_node("tester", tester, "静态检查验证修复是否真正生效")

    graph.set_entry("coder")
    graph.add_edge("coder", "reviewer")
    graph.add_conditional_edge(
        "reviewer",
        condition=_has_issues,
        targets={"有Bug": "fixer", "无Bug": "tester"},
    )
    graph.add_edge("fixer", "reviewer")   # 修复后回到审查，形成受控循环
    graph.add_edge("tester", END)
    graph.validate()
    return graph
