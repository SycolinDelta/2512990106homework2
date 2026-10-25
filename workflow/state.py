"""Workflow 的共享状态（state）。

所有 Agent 都读写同一份 WorkflowState —— 这就是「状态管理」的核心。
整体模型类似「黑板架构（Blackboard）」：

    coder / reviewer / fixer / tester
              ↘     ↓     ↓     ↙
            WorkflowState（共享黑板）
              ↖     ↑     ↑     ↗

- 各 Agent 只写自己负责的字段（例如 reviewer 只写 review）；
- 任何 Agent 都能读到前面 Agent 留下的产物（例如 fixer 读 review 的结论）；
- messages 记录所有 Agent 间消息，logger 把它们同时写进执行日志。

重要约束：本状态只保存「代码文本」，不对应磁盘上的任何文件；
test.cpp 这类样例文件全程只读，修复结果只存在内存、只打印到终端。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from workflow.message import Message


@dataclass
class WorkflowState:
    """一次 Workflow 运行的全部状态。"""

    # ---------- 输入 ----------
    raw_input: str = ""               # 用户原始输入（代码文本，或文件路径）
    source_name: str = "<input>"      # 输入来源名，例如 test.cpp（仅用于显示）
    language: str = "cpp"             # 代码语言，决定给哪个检查器

    # ---------- 各 Agent 的产物 ----------
    original_code: str = ""           # coder 整理后的原始代码（只读快照）
    code: str = ""                    # 当前最新代码：fixer 每修复一次就更新这里
    review: Optional[Dict[str, Any]] = None    # reviewer 的审查结论
    fix_report: Optional[Dict[str, Any]] = None  # fixer 的修复说明（最近一次）
    test_result: Optional[Dict[str, Any]] = None  # tester 的验证结论

    # ---------- 流程控制 ----------
    round: int = 0                    # 当前第几轮「审查-修复」循环
    max_rounds: int = 3               # 循环上限，保证一定会终止
    finished: bool = False            # Workflow 是否已结束
    stop_reason: str = ""             # 结束原因：passed / max_rounds / error
    error: str = ""                   # 出错时的错误信息

    # ---------- 通信与日志 ----------
    messages: List[Message] = field(default_factory=list)   # 全部 Agent 间消息
    trace: List[Dict[str, Any]] = field(default_factory=list)  # 事件轨迹（执行日志）

    # ---------------------------------------------------------------
    # 消息投递
    # ---------------------------------------------------------------
    def send(self, msg: Message) -> None:
        """投递一条消息：进入收件箱，同时记录到事件轨迹。"""
        self.messages.append(msg)
        self.log("message", sender=msg.sender, receiver=msg.receiver,
                 msg_type=msg.msg_type, content=msg.content)

    def mailbox(self, receiver: str, msg_type: Optional[str] = None) -> List[Message]:
        """读取某个 Agent 收到的消息（可按类型过滤）。"""
        return [m for m in self.messages
                if m.receiver == receiver and (msg_type is None or m.msg_type == msg_type)]

    def latest_payload(self, receiver: str, msg_type: str) -> Dict[str, Any]:
        """取最近一条某类型消息的 payload，没有则返回空字典。"""
        for m in reversed(self.messages):
            if m.receiver == receiver and m.msg_type == msg_type:
                return m.payload
        return {}

    # ---------------------------------------------------------------
    # 事件轨迹
    # ---------------------------------------------------------------
    def log(self, event: str, **fields: Any) -> None:
        """追加一条事件轨迹，带时间戳和当前轮次。"""
        record = {"ts": round(time.time(), 3), "round": self.round, "event": event}
        record.update(fields)
        self.trace.append(record)

    # ---------------------------------------------------------------
    # 快照与序列化
    # ---------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        """给执行日志用的状态快照（不含 messages，messages 单独写）。"""
        return {
            "source_name": self.source_name,
            "round": self.round,
            "max_rounds": self.max_rounds,
            "finished": self.finished,
            "stop_reason": self.stop_reason,
            "error": self.error,
            "issue_count": len((self.review or {}).get("issues", [])),
            "last_fix_change_count": len((self.fix_report or {}).get("changes", [])),
            "code_changed": self.code != self.original_code,
        }

    def to_json(self, path: str) -> None:
        """把完整执行记录写成 JSON 文件（事件轨迹 + 全部消息 + 最终代码）。"""
        data = {
            "snapshot": self.snapshot(),
            "trace": self.trace,
            "messages": [m.to_dict() for m in self.messages],
            "final_code": self.code,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
