"""tester Agent：验证修复是否真正生效。

不依赖大模型，只用确定性方式核对：
1. 修复前后各跑一遍静态检查，对比问题编号集合，得到「已修复 / 本次新引入 / 仍未修复」；
2. 逐行对比原始代码与修复后代码，统计实际改动的行数（防止模型声称修了但其实没改）。

结论写入 state.test_result，并作为最终输出里「验证结论」一节的数据来源。
本节点只读内存中的代码字符串，不会写任何文件。
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List, Set

from agents.base import BaseAgent
from tools.cpp_static_checker import check_cpp
from workflow.message import MSG_TEST_RESULT
from workflow.state import WorkflowState


class TesterAgent(BaseAgent):
    """验证节点。"""

    name = "tester"

    def handle(self, state: WorkflowState) -> None:
        original = state.original_code
        fixed = state.code

        before: Set[str] = set()
        after: Set[str] = set()
        if state.language == "cpp":
            before = {i.key for i in check_cpp(original)}
            after = {i.key for i in check_cpp(fixed)}

        # 1) 差异统计：只统计真正的改动行（忽略空白差异）
        diff_lines = [l for l in difflib.unified_diff(
            original.splitlines(), fixed.splitlines(), lineterm="", n=0)
            if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]

        # 2) 分类结论
        resolved = sorted(before - after)
        remaining = sorted(after)
        inherited_residual = sorted(after & before)   # 修复前后都存在的问题 = 真没修掉
        introduced = sorted(after - before)           # 修复后才出现的问题 = 改坏了

        passed = not remaining
        if passed:
            verdict = "验证通过：静态检查未再发现问题，修复结果可以采纳。"
        else:
            verdict = (f"验证未完全通过：仍有 {len(remaining)} 个静态检查问题"
                       f"（{'其中 ' + str(len(introduced)) + ' 个为修复过程新引入' if introduced else '均为原代码遗留'}）。")

        result: Dict[str, Any] = {
            "passed": passed,
            "verdict": verdict,
            "rounds": state.round,
            "before_issues": len(before),
            "after_issues": len(remaining),
            "resolved": resolved,
            "introduced": introduced,
            "remaining": remaining,
            "changed_line_count": len([l for l in diff_lines if l.startswith("+")]),
            "changed": fixed.strip() != original.strip(),
        }
        state.test_result = result
        state.log("test_done", **{k: result[k] for k in
                                  ("passed", "before_issues", "after_issues", "changed_line_count")})

        self.send(
            state,
            receiver="orchestrator",
            msg_type=MSG_TEST_RESULT,
            content=verdict,
            **result,
        )
