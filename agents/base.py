"""Agent 基类与公共工具。

所有 Workflow 节点都是「Agent」：接收 WorkflowState、读写共享状态、发送消息。

本模块提供：
1. BaseAgent：统一的 Agent 抽象（name / receive / handle / send）；
2. LLMClient：对 LangChain ChatOpenAI 的一层薄封装，负责调用大模型、
   解析返回的 JSON、失败重试、以及没有 API Key 时的明确报错；
3. 代码块解析工具：从模型回复里抠出 ```cpp ... ``` 代码块。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from workflow.message import Message
from workflow.state import WorkflowState


# ----------------------------------------------------------------------
# 大模型调用
# ----------------------------------------------------------------------
class LLMError(RuntimeError):
    """大模型调用失败（网络、鉴权、返回格式不对等）。"""


class LLMClient:
    """封装智谱 glm（OpenAI 兼容接口）的调用。

    与 Homework1 完全相同的接入方式：langchain_openai.ChatOpenAI + .env 配置。
    """

    def __init__(self, temperature: float = 0.2, model: Optional[str] = None):
        self.temperature = temperature
        self.model = model or os.getenv("LLM_MODEL", "glm-4-flash")
        self._client = None

    @property
    def client(self):
        """懒加载 ChatOpenAI（没装依赖时只在真正调用时才报错）。"""
        if self._client is None:
            api_key = os.getenv("LLM_API_KEY")
            if not api_key:
                raise LLMError("未配置 LLM_API_KEY，请检查 .env 文件")
            try:
                from langchain_openai import ChatOpenAI
            except ImportError as err:  # pragma: no cover - 取决于用户环境
                raise LLMError(
                    "未安装 langchain_openai，请先执行："
                    "pip install -r requirements.txt"
                ) from err
            self._client = ChatOpenAI(
                api_key=api_key,
                base_url=os.getenv("LLM_BASE_URL"),
                model=self.model,
                temperature=self.temperature,
            )
        return self._client

    def chat(self, system_prompt: str, user_prompt: str,
             attempt: int = 2) -> str:
        """发一次对话，返回文本。失败自动重试 attempt 次。"""
        last_error = ""
        for _ in range(attempt):
            try:
                resp = self.client.invoke([
                    ("system", system_prompt),
                    ("user", user_prompt),
                ])
                text = resp.content if isinstance(resp.content, str) else str(resp.content)
                if text and text.strip():
                    return text
                last_error = "模型返回空内容"
            except Exception as err:  # noqa: BLE001
                last_error = f"{type(err).__name__}: {err}"
        raise LLMError(last_error)

    def chat_json(self, system_prompt: str, user_prompt: str,
                  attempt: int = 2) -> Dict[str, Any]:
        """要求模型输出 JSON，并解析成字典。"""
        text = self.chat(system_prompt, user_prompt, attempt=attempt)
        return parse_json_block(text)


def parse_json_block(text: str) -> Dict[str, Any]:
    """从模型回复中解析 JSON 对象（容忍 ```json 包裹与前后多余文字）。"""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    for candidate in (cleaned,):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    # 退而求其次：截取第一个 { 到最后一个 }
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        data = json.loads(cleaned[start:end + 1])
        if isinstance(data, dict):
            return data
    raise LLMError("模型未返回合法 JSON")


def extract_code_block(text: str) -> str:
    """从模型回复中提取最大的代码块；没有代码块时返回原文。"""
    blocks = re.findall(r"```[a-zA-Z+#]*\s*\n(.*?)```", text, re.S)
    if not blocks:
        return text.strip()
    return max(blocks, key=len).rstrip() + "\n"


# ----------------------------------------------------------------------
# Agent 基类
# ----------------------------------------------------------------------
class BaseAgent:
    """一个 Workflow 节点 = 一个 Agent。

    子类只需实现 handle(state)，在内部：
        - 从共享状态读取上游产物；
        - 通过 self.send(state, ...) 把结果作为消息投递给下游；
        - 把产物写回共享状态自己的字段。
    """

    name: str = "agent"

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm

    # ------------------------------------------------------------------
    def __call__(self, state: WorkflowState) -> None:
        """编排器调用的入口。"""
        self.handle(state)

    def handle(self, state: WorkflowState) -> None:  # pragma: no cover - 抽象
        raise NotImplementedError

    def send(self, state: WorkflowState, receiver: str, msg_type: str,
             content: str = "", **payload: Any) -> None:
        """向共享状态投递一条消息。"""
        state.send(Message(sender=self.name, receiver=receiver, msg_type=msg_type,
                           content=content, payload=payload))


def issue_lines(issues: List[Dict[str, Any]], limit: int = 20) -> str:
    """把静态检查结果格式化成提示词里的一段文字。"""
    if not issues:
        return "（确定性静态检查未发现问题）"
    lines = []
    for i, issue in enumerate(issues[:limit], 1):
        lines.append(
            f"{i}. [{issue['id']}] 第{issue['line_no']}行：`{issue['line']}`\n"
            f"   问题：{issue['title']}\n"
            f"   说明：{issue['explanation']}\n"
            f"   修复：{issue['fix']}"
        )
    if len(issues) > limit:
        lines.append(f"...（还有 {len(issues) - limit} 条未列出）")
    return "\n".join(lines)
