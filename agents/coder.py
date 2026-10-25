"""coder Agent：Workflow 的第一个节点。

职责：接收用户提交的代码（或文件路径），把它登记为本次 Workflow 的「原始代码」，
并打包成消息发送给下游的 reviewer。

它不做任何修改：original_code 是只读快照，后续所有修复都只改 state.code，
保证「原始代码」与「修复后代码」始终可以对比。
"""

from __future__ import annotations

import os

from agents.base import BaseAgent
from tools.file_reader import detect_language, read_code_file
from workflow.message import MSG_CODE_READY
from workflow.state import WorkflowState


class CoderAgent(BaseAgent):
    """登记输入代码，交给审查 Agent。"""

    name = "coder"

    def __init__(self, llm=None):
        super().__init__(llm)

    def handle(self, state: WorkflowState) -> None:
        # 1) 如果输入是文件路径（前端已经做过确定性识别），读取文件内容
        code = state.raw_input
        if state.source_name not in ("<input>", "") and os.path.isfile(state.source_name):
            result = read_code_file(state.source_name)
            if not result.startswith("文件读取成功"):
                raise ValueError(result)
            code = result.split("\n", 1)[1] if "\n" in result else result
            state.language = detect_language(state.source_name)

        code = code.replace("\r\n", "\n").strip("\n") + "\n"
        if not code.strip():
            raise ValueError("待审查代码为空")

        # 2) 写入共享状态：original_code 为只读快照，code 为当前工作副本
        state.original_code = code
        state.code = code
        state.round = 0
        state.review = None
        state.fix_report = None
        state.test_result = None

        # 3) 发送消息给 reviewer（Agent 间通信）
        self.send(
            state,
            receiver="reviewer",
            msg_type=MSG_CODE_READY,
            content=f"待审查代码已就绪（来源 {state.source_name}，语言 {state.language}，"
                    f"共 {len(code.splitlines())} 行）",
            code=code,
            language=state.language,
        )
