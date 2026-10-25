"""Agent 间通信的消息协议。

Workflow 里两个 Agent 之间不直接互相调用函数，而是通过消息（Message）交流：
发送方把消息投递到 WorkflowState 的收件箱里，接收方从收件箱取走。
这样做的好处：

1. 消息全部留痕，可以完整回放「谁在什么时候说了什么」，便于排查和演示；
2. 任何 Agent 都可以替换成另一种实现（真 LLM / Mock LLM / 规则引擎），
   只要遵守同一套消息格式即可，编排层完全不用改（可扩展性）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict

# 消息类型常量：用固定字符串，避免各 Agent 各写一套拼写
MSG_CODE_READY = "CODE_READY"        # coder -> reviewer：待审查的代码已就绪
MSG_REVIEW_RESULT = "REVIEW_RESULT"  # reviewer -> orchestrator/fixer：审查结论
MSG_FIX_DONE = "FIX_DONE"            # fixer -> reviewer：修复后的代码
MSG_TEST_RESULT = "TEST_RESULT"      # tester -> orchestrator：验证结论
MSG_GENERIC = "MESSAGE"              # 其它普通文本消息


@dataclass
class Message:
    """一条 Agent 间消息。"""

    sender: str                       # 发送方 Agent 名称
    receiver: str                     # 接收方 Agent 名称
    msg_type: str                     # 消息类型，见上面的常量
    content: str = ""                 # 人类可读的正文（写进执行日志用）
    payload: Dict[str, Any] = field(default_factory=dict)  # 结构化数据
    created_at: float = field(default_factory=time.time)

    def brief(self, limit: int = 120) -> str:
        """返回适合打印的一行摘要。"""
        text = " ".join(self.content.split())
        if len(text) > limit:
            text = text[:limit] + "..."
        return f"[{self.msg_type}] {self.sender} -> {self.receiver}: {text}"

    def to_dict(self) -> Dict[str, Any]:
        """转成可 JSON 序列化的字典（执行日志、回放用）。"""
        return {
            "sender": self.sender,
            "receiver": self.receiver,
            "msg_type": self.msg_type,
            "content": self.content,
            "payload": self.payload,
            "created_at": self.created_at,
        }
