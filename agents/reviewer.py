"""reviewer Agent：审查当前代码，产出「必须修复的问题清单」。

复用 Homework1 沉淀下来的审查经验：
1. 审查必须基于源码原文，引用的行必须与源码逐字一致；
2. 不确定的问题不计为 Bug，宁可少报不可错报；
3. 每个问题用「位置 → 问题本质 → 修复方式」描述。

在 Homework2 里额外增加一条客观依据：确定性静态检查器的结果会一并交给模型，
两者合并去重后形成最终问题清单（has_issues 决定流程走「修复」还是「直接验证」）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from agents.base import BaseAgent, issue_lines
from tools.cpp_static_checker import check_cpp
from workflow.message import MSG_CODE_READY, MSG_FIX_DONE, MSG_REVIEW_RESULT
from workflow.state import WorkflowState

REVIEW_SYSTEM_PROMPT = """你是代码审查助手，负责在自动化修复流程中找出「必须修复的问题」。
工作规则：
1. 严格基于给出的源码原文：引用代码时必须与源码逐字一致，不得编造源码中不存在的代码；
2. 只报告确定存在的问题；不确定的内容一律不报，宁可少报不可错报；
3. 每个问题用「位置 → 问题本质 → 修复方式」描述，明确指出错误本质；
4. 与编译器/运行结果相关的问题（编译错误、空指针崩溃、退出码错误、未定义行为、资源泄漏等）优先；
5. 只输出 JSON，不要输出多余解释。"""

REVIEW_USER_TEMPLATE = """请审查下面这段{language}代码，找出必须修复的问题。

【待审查代码】
```{language}
{code}
```

【确定性静态检查的参考结果】（高置信度，可直接采纳；如与源码不符请以源码为准）
{static_issues}

【输出格式】严格输出如下 JSON：
{{
  "has_issues": true 或 false,
  "summary": "一句话概括代码当前的主要问题",
  "issues": [
    {{"line_no": 行号(整数), "line": "该行源码原文", "title": "问题标题",
      "explanation": "问题本质说明", "fix": "修复方式"}}
  ]
}}
如果没有需要修复的问题，输出 {{"has_issues": false, "summary": "...", "issues": []}}。"""


def _merge_issues(llm_issues: List[Dict[str, Any]],
                  static_issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """合并模型发现的问题和静态检查发现的问题（按行号+标题去重）。"""
    merged: List[Dict[str, Any]] = []
    seen: set = set()

    def _key(item: Dict[str, Any]) -> str:
        return f"{item.get('line_no')}|{(item.get('title') or '').strip()}"

    for item in static_issues:
        item = dict(item)
        item.setdefault("source", "static")
        merged.append(item)
        seen.add(_key(item))
    for item in llm_issues:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        item.setdefault("source", "llm")
        if _key(item) in seen:
            continue
        merged.append(item)
        seen.add(_key(item))
    return merged


class ReviewerAgent(BaseAgent):
    """审查节点。"""

    name = "reviewer"

    def handle(self, state: WorkflowState) -> None:
        state.round += 1
        code = state.code

        # 1) 先跑确定性静态检查，作为客观依据
        static_issues = [issue.to_dict() for issue in check_cpp(code)] if state.language == "cpp" else []

        # 2) 让大模型做语义审查（有 LLM 时）
        llm_issues: List[Dict[str, Any]] = []
        summary = ""
        if self.llm is not None:
            result = self.llm.chat_json(
                REVIEW_SYSTEM_PROMPT,
                REVIEW_USER_TEMPLATE.format(
                    language=state.language,
                    code=code,
                    static_issues=issue_lines(static_issues),
                ),
            )
            llm_issues = result.get("issues") or []
            summary = str(result.get("summary") or "")
            # 模型明确判断无问题时，也不推翻静态检查的结果
            if result.get("has_issues") is False and not static_issues:
                llm_issues = []

        issues = _merge_issues(llm_issues, static_issues)
        has_issues = bool(issues)

        if not summary:
            summary = ("静态检查发现 %d 个问题，需要修复" % len(issues)) if issues else "未发现问题"

        # 3) 写回共享状态
        state.review = {
            "round": state.round,
            "has_issues": has_issues,
            "summary": summary,
            "issues": issues,
            "static_issues": static_issues,
        }
        state.log("review_done", round=state.round, has_issues=has_issues,
                  issue_count=len(issues))

        # 4) 广播审查结论（下游 fixer / tester 都从这里读）
        self.send(
            state,
            receiver="fixer" if has_issues else "tester",
            msg_type=MSG_REVIEW_RESULT,
            content=(f"第 {state.round} 轮审查：{'发现 ' + str(len(issues)) + ' 个问题' if has_issues else '未发现问题'}"
                     f"（{summary}）"),
            has_issues=has_issues,
            issues=issues,
            round=state.round,
        )

    # ------------------------------------------------------------------
    def receive_code(self, state: WorkflowState) -> str:
        """从收件箱取「当前要审查的代码」：优先用 fixer 修好的版本。"""
        fixed = state.latest_payload(self.name, MSG_FIX_DONE)
        if fixed.get("code"):
            return fixed["code"]
        ready = state.latest_payload(self.name, MSG_CODE_READY)
        return ready.get("code", state.code)
