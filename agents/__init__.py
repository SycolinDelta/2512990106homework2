"""Agent 包：Workflow 中的各个节点。

每个 Agent 都遵循同一套接口（BaseAgent）：
    输入：共享的 WorkflowState —— 从里面读上游产物
    输出：写回 WorkflowState 自己的字段 + 向收件箱投递一条消息
因此任何一个 Agent 都可以被替换（真 LLM / Mock / 规则引擎），编排层无需改动。
"""

from agents.base import BaseAgent, LLMClient, LLMError
from agents.coder import CoderAgent
from agents.fixer import FixerAgent
from agents.reviewer import ReviewerAgent
from agents.tester import TesterAgent

__all__ = [
    "BaseAgent", "LLMClient", "LLMError",
    "CoderAgent", "ReviewerAgent", "FixerAgent", "TesterAgent",
]
