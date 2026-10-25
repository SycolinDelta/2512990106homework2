"""结果渲染：把 Workflow 的最终状态格式化成终端输出。

Homework2 与 Homework1 的区别就在这里：
Homework1 输出「修改建议 + 注释后的代码」，Homework2 输出**自行修复后的结果**。

输出固定三部分：
    一、修复概览 —— 修了什么、为什么
    二、修复后的完整代码 —— 可直接复制使用；源文件本身不会被改动
    三、验证结论 —— 确定性检查的客观核对结果
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List

from workflow.state import WorkflowState

# 代码块的显示语言
_LANG_FENCE = {"cpp": "cpp", "other": "text"}


def _first_review(state: WorkflowState) -> Dict[str, Any]:
    """取第一轮（修复前）的审查记录。"""
    for record in state.trace:
        if record.get("event") == "review_done":
            return record
    return {}


def _round_log(state: WorkflowState) -> List[str]:
    """按轮次汇总「审查 → 修复」。"""
    lines: List[str] = []
    for record in state.trace:
        event = record.get("event")
        if event == "review_done":
            if record.get("has_issues"):
                lines.append(f"第{record['round']}轮审查：发现 {record['issue_count']} 个问题")
            else:
                lines.append(f"第{record['round']}轮审查：未发现问题")
        elif event == "fix_done":
            lines.append(f"第{record['round']}轮修复：{record['change_count']} 处改动"
                         f"（来源：{record.get('source', '未注明')}）")
    return lines


def render_flow_trace(state: WorkflowState) -> str:
    """执行过程：节点顺序 + 每轮循环的审/修结果。"""
    order: List[str] = []
    for record in state.trace:
        if record.get("event") == "node_done":
            order.append(record.get("node", ""))
    steps = " → ".join(order) if order else "(无)"

    out = ["【执行过程】", f"  节点执行顺序：{steps}"]
    for item in _round_log(state):
        out.append(f"  · {item}")
    return "\n".join(out)


def _change_table(changes: List[Dict[str, Any]]) -> str:
    """把修复记录渲染成「位置 → 修改内容」。"""
    if not changes:
        return "  （没有产生代码改动）"
    out: List[str] = []
    for i, change in enumerate(changes, 1):
        line_no = change.get("line_no", "-")
        before = str(change.get("before", "")).strip().replace("\n", " ⏎ ")
        after = str(change.get("after", "")).strip().replace("\n", " ⏎ ")
        reason = str(change.get("reason", "")).strip()
        out.append(f"  {i}. 原第 {line_no} 行")
        if before and before != after:
            out.append(f"     修改前：{before}")
            out.append(f"     修改后：{after}")
        out.append(f"     原因：{reason}")
    return "\n".join(out)


def render_result(state: WorkflowState) -> str:
    """生成最终输出文本（三部分 + 执行过程 + 差异）。"""
    review = state.review or {}
    fix = state.fix_report or {}
    test = state.test_result or {}
    summary = str(review.get("summary") or "")
    language = _LANG_FENCE.get(state.language, "text")
    first = _first_review(state)

    changed = state.code.strip() != state.original_code.strip()
    before_issues = test.get("before_issues", first.get("issue_count", len(review.get("issues", []))))

    blocks: List[str] = []
    blocks.append("=" * 72)
    blocks.append(f"Workflow 结果：{state.source_name}（{state.stop_reason or 'completed'}，"
                  f"共 {state.round} 轮审查-修复）")
    blocks.append("=" * 72)

    # ---------------- 一、修复概览 ----------------
    blocks.append("\n一、修复概览")
    blocks.append(f"  原始问题：{before_issues} 个")
    if not first:
        blocks.append("  审查结论：（未执行审查）")
    elif not first.get("has_issues"):
        blocks.append("  审查结论：原始代码未发现需要修复的问题")
    elif summary:
        blocks.append(f"  审查结论：{summary}")
    else:
        blocks.append("  审查结论：发现需要修复的问题（详见下方修复清单）")
    blocks.append(f"  修复来源：{fix.get('source') or '无'}")
    blocks.append(f"  代码是否改动：{'是' if changed else '否'}（改动行数约 {test.get('changed_line_count', 0)}）")
    blocks.append("  修复清单：")
    blocks.append(_change_table(fix.get("changes", [])))

    if state.error:
        blocks.append(f"\n  ⚠ 流程中止原因：{state.error}")

    # ---------------- 二、修复后的完整代码 ----------------
    blocks.append("\n二、修复后的完整代码")
    blocks.append(f"  （以下代码只输出在终端，源文件 {state.source_name} 未被修改）")
    blocks.append(f"```{language}")
    blocks.append(state.code.rstrip("\n"))
    blocks.append("```")

    # ---------------- 三、验证结论 ----------------
    blocks.append("\n三、验证结论")
    if not test:
        blocks.append("  （未执行验证）")
    else:
        blocks.append(f"  {test.get('verdict', '')}")
        blocks.append(f"  修复前静态检查问题数：{test.get('before_issues', 0)}")
        blocks.append(f"  修复后静态检查问题数：{test.get('after_issues', 0)}")
        resolved = test.get("resolved") or []
        blocks.append(f"  已修复：{', '.join(resolved) if resolved else '（无）'}")
        residual = test.get("remaining") or []
        blocks.append(f"  仍未修复：{', '.join(residual) if residual else '（无）'}")
        introduced = test.get("introduced") or []
        blocks.append(f"  本次新引入：{', '.join(introduced) if introduced else '（无）'}")

    # ---------------- 附：执行过程与差异 ----------------
    blocks.append("")
    blocks.append(render_flow_trace(state))

    if changed:
        blocks.append("\n【修复前后差异】")
        diff = list(difflib.unified_diff(
            state.original_code.splitlines(), state.code.splitlines(),
            fromfile=f"{state.source_name} (原始)", tofile="修复后", lineterm="", n=1))
        blocks.extend(diff[:80])
        if len(diff) > 80:
            blocks.append("...（差异过长，仅显示前 80 行，完整记录见 --log 输出的执行日志）")

    return "\n".join(blocks)
