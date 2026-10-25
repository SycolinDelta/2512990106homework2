"""fixer Agent：根据审查结论自动修复代码。

流程里最体现「自行修复」的一环：
1. 读取 reviewer 给出的问题清单；
2. 调用大模型输出修复后的完整代码 + 逐条修改说明；
3. 用确定性检查器复核修复结果——如果静态检查还能测出问题，说明模型漏改，
   此时用 apply_safe_fixes 兜底补齐（保守、高置信度），保证流程一定能收敛；
4. 只把新代码放回共享状态，绝不写回源文件。
"""

from __future__ import annotations

from typing import Any, Dict, List

from agents.base import BaseAgent, extract_code_block, issue_lines
from tools.cpp_static_checker import apply_safe_fixes, check_cpp
from workflow.message import MSG_FIX_DONE, MSG_REVIEW_RESULT
from workflow.state import WorkflowState

FIX_SYSTEM_PROMPT = """你是代码修复助手，负责把审查发现的问题直接改掉。
工作规则：
1. 输出修复后的**完整**代码，不要省略任何部分，不要使用“…”之类的省略号；
2. 除修复问题所必需的改动外，不要改动原有逻辑、变量命名和代码风格；
3. 每一处非注释性改动都必须在修改说明里列出，与代码一一对应；
4. 保持原有注释和输出文本不变；
5. 只输出 JSON，不要输出多余解释。"""

FIX_USER_TEMPLATE = """请修复下面代码中被审查出的所有问题。

【当前代码（{language}）】
```{language}
{code}
```

【必须修复的问题】
{issues}

【输出格式】严格输出如下 JSON：
{{
  "fixed_code": "修复后的完整代码（字符串，用 \\n 换行）",
  "changes": [
    {{"line_no": 原代码中的问题行号, "before": "修改前的源码", "after": "修改后的源码", "reason": "为什么这样改"}}
  ]
}}"""


class FixerAgent(BaseAgent):
    """修复节点。"""

    name = "fixer"

    def handle(self, state: WorkflowState) -> None:
        review = state.review or {}
        issues: List[Dict[str, Any]] = review.get("issues", [])
        code = state.code
        changes: List[Dict[str, Any]] = []
        fixed_code = code
        source = "llm"

        # 1) 大模型修复
        if self.llm is not None:
            try:
                result = self.llm.chat_json(
                    FIX_SYSTEM_PROMPT,
                    FIX_USER_TEMPLATE.format(
                        language=state.language,
                        code=code,
                        issues=issue_lines(issues),
                    ),
                )
                candidate = result.get("fixed_code") or ""
                candidate = extract_code_block(candidate) if "```" in candidate else candidate
                if candidate and candidate.strip() and candidate.strip() != code.strip():
                    fixed_code = candidate if candidate.endswith("\n") else candidate + "\n"
                changes = [c for c in (result.get("changes") or []) if isinstance(c, dict)]
            except Exception as err:  # noqa: BLE001 —— 模型修不好时走兜底
                state.log("fixer_llm_failed", error=f"{type(err).__name__}: {err}")
                source = "rule"

        # 2) 确定性复核：静态检查还能测出问题 => 模型漏改，用规则兜底补齐
        if state.language == "cpp":
            residual = check_cpp(fixed_code)
            if residual:
                safe = apply_safe_fixes(fixed_code)
                fixed_code = safe["code"] if safe["code"].endswith("\n") else safe["code"] + "\n"
                changes.extend(safe["changes"])
                source = "llm+rules" if source == "llm" else "rule"

        if not fixed_code.endswith("\n"):
            fixed_code += "\n"

        # 3) 写回共享状态
        state.code = fixed_code
        state.fix_report = {
            "round": state.round,
            "source": source,
            "changes": changes,
            "fixed_code": fixed_code,
        }
        state.log("fix_done", round=state.round, change_count=len(changes), source=source)

        # 4) 把修复结果送回 reviewer，触发下一轮审查（循环）
        self.send(
            state,
            receiver="reviewer",
            msg_type=MSG_FIX_DONE,
            content=f"第 {state.round} 轮修复完成，共 {len(changes)} 处改动（来源：{source}）",
            code=fixed_code,
            changes=changes,
            round=state.round,
        )
