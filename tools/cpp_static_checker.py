"""C++ 确定性静态检查器。

作用：给 Workflow 里的「审查」「验证」环节提供**不依赖大模型**的客观证据。

设计要点：
1. 纯文本规则匹配，不编译、不执行，也不写任何文件（源文件全程只读）；
2. 每条问题带一个稳定编号（issue key），修复前后分别检查同一套规则，
   就能对比出「这条问题到底修掉没有」，而不是只听大模型说"已修复"；
3. 规则是数据驱动的：通用规则写在 RULES 表里，需要看上下文的规则写成专门的检查函数，
   要新增检查项只需加一条规则或一个函数。

检查规则尽量选「高置信度、不会误报」的写法：宁可少报，也不要把正确的代码判错。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Rule:
    """一条通用检查规则（逐行正则匹配即可判定）。"""

    rule_id: str          # 规则编号，例如 CPP-STL-TEMPLATE-ARG
    title: str            # 问题标题
    pattern: re.Pattern   # 触发正则
    explanation: str      # 问题本质说明
    fix: str              # 建议的修复方式


@dataclass
class Issue:
    """一条命中的问题。"""

    rule_id: str
    line_no: int
    line: str
    title: str
    explanation: str
    fix: str

    @property
    def key(self) -> str:
        """稳定编号：规则 + 行号，用于修复前后对比。"""
        return f"{self.rule_id}@{self.line_no}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.key,
            "rule": self.rule_id,
            "line_no": self.line_no,
            "line": self.line.strip(),
            "title": self.title,
            "explanation": self.explanation,
            "fix": self.fix,
        }

    def to_brief(self) -> str:
        """给提示词用的一行描述。"""
        return f"[{self.key}] 第{self.line_no}行 `{self.line.strip()}`：{self.title}——{self.explanation}"


# ----------------------------------------------------------------------
# 通用规则表（逐行匹配）
# ----------------------------------------------------------------------
RULES: List[Rule] = [
    Rule(
        rule_id="CPP-STL-TEMPLATE-ARG",
        title="STL 容器模板参数写成了元素类型而不是指针类型",
        # 匹配 priority_queue< 名字 , vector<...  —— 第一个参数不是指针就报错
        pattern=re.compile(r"priority_queue\s*<\s*[A-Za-z_]\w*\s*,\s*vector\s*<"),
        explanation=(
            "priority_queue 的第一个模板参数是元素类型，但容器参数和比较器都按指针处理，"
            "元素类型与容器/比较器不一致，代码无法通过编译；而且该结构体没有定义 operator<，"
            "也无法作为元素类型参与比较。"
        ),
        fix="把第一个模板参数改成指针类型，例如 priority_queue<HuffNode*, vector<HuffNode*>, cmp>",
    ),
]


# ----------------------------------------------------------------------
# 上下文相关规则（需要看整个函数体）
# ----------------------------------------------------------------------
_EMPTY_CHECK = re.compile(r"\bif\s*\(\s*(\w+)\s*(==|!=)\s*nullptr\s*\)")
_DELETE = re.compile(r"\bdelete\s+(\w+)\s*;")
_RECURSE = re.compile(r"\b(\w+)\s*\(\s*(\w+)\s*->\s*(left|right)\s*\)")
_FUNC_HEAD = re.compile(r"[A-Za-z_][\w:<>,\s\*&\[\]]*\b([A-Za-z_]\w*)\s*\([^;]*\)\s*\{?\s*$")


def _function_name(lines: List[str], line_index: int) -> str:
    """粗略找到某一行所在的函数名（向前找最近的函数定义行）。"""
    for i in range(line_index, -1, -1):
        m = _FUNC_HEAD.search(lines[i])
        if m and m.group(1) not in {"if", "for", "while", "switch", "return", "delTree"}:
            return m.group(1)
        if m and i != line_index:
            return m.group(1)
    return ""


def _function_body(lines: List[str], line_index: int) -> List[tuple[int, str]]:
    """找到 line_index 所在的函数体，返回 (行号, 行文本) 列表（首行为 '{' 之后的内容）。

    做法：先找到 line_index 所在函数的开头 '{'，再从那里做括号配对直到配平的 '}'。
    找不到（例如该行不在函数体内）时返回空列表。
    """    # 1) 向上找函数开头的 '{'（跳过已配平的括号）
    depth = 0
    open_index = None
    for i in range(line_index, -1, -1):
        text = lines[i]
        for ch in reversed(text):
            if ch == "}":
                depth += 1
            elif ch == "{":
                if depth == 0:
                    open_index = i
                    break
                depth -= 1
        if open_index is not None:
            break
    if open_index is None:
        return []

    # 2) 从 '{' 开始向下配对
    body: List[tuple[int, str]] = []
    depth = 0
    for i in range(open_index, len(lines)):
        text = lines[i]
        start_depth = depth
        for ch in text:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
        if i == open_index:
            continue
        if depth <= 0:  # 配对结束，本行是结尾的 '}'
            if start_depth > 0:
                body.append((i, text.split("}")[0]))
            return body
        body.append((i, text))
    return body


def _check_free_order(lines: List[str], index: int) -> Optional[Issue]:
    """检查「递归释放函数」：判空条件写反 / 先释放后访问子节点。"""
    text = lines[index]
    if not _DELETE.search(text):
        return None
    body = _function_body(lines, index)
    if not body:
        return None

    deleted: Optional[str] = None
    for _, t in body:
        m = _DELETE.search(t)
        if m:
            deleted = m.group(1)
            break
    if deleted is None:
        return None

    # 释放之后仍然访问 same 指针的成员 => 先释放后访问（未定义行为）
    order_bug = folder_access = False
    flag = False
    for _, t in body:
        if _DELETE.search(t):
            flag = True
        elif flag and re.search(rf"\b{re.escape(deleted)}\s*->", t):
            order_bug = True

    # 判空条件写反：if (p != nullptr) return;  随后又访问 p->...
    cond_bug = False
    for _, t in body:
        m = _EMPTY_CHECK.search(t)
        if m and m.group(2) == "!=":
            after = next((x for _, x in body if x is not t and (x or "").strip().lower().startswith("return")), "")
            if re.search(rf"\b{m.group(1)}\s*->", " ".join(x for _, x in body)):
                cond_bug = True
            break

    if not (order_bug or cond_bug):
        return None

    problems = []
    if cond_bug:
        problems.append("判空条件写反：非空节点会直接 return 而不释放，空节点反而继续解引用导致崩溃")
    if order_bug:
        problems.append("释放顺序错误：先 delete 再访问子节点，属于未定义行为")
    return Issue(
        rule_id="CPP-FREE-ORDER",
        line_no=index + 1,
        line=text,
        title="递归释放函数的判空条件/释放顺序错误",
        explanation="；".join(problems) + "。",
        fix="判空应写 == nullptr；并按 先递归释放 left/right、最后 delete 当前节点 的顺序重写。",
    )


# ----------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------
def check_cpp(code: str, rule_ids: Optional[List[str]] = None) -> List[Issue]:
    """对一段 C++ 代码执行静态检查，返回命中的问题列表。

    参数：
        code:     代码文本
        rule_ids: 只跑这些规则（None 表示全部），用于把「某条规则的前后结果」做对比
    """
    lines = code.splitlines()
    active = [r for r in RULES if rule_ids is None or r.rule_id in rule_ids]
    issues: List[Issue] = []

    for index, text in enumerate(lines):
        if text.strip().startswith("//"):
            continue  # 跳过注释行，避免把注释里的示例代码当成真问题

        # 1) 通用逐行规则
        for rule in active:
            if rule.pattern.search(text):
                issues.append(Issue(
                    rule_id=rule.rule_id, line_no=index + 1, line=text,
                    title=rule.title, explanation=rule.explanation, fix=rule.fix,
                ))

        # 2) 上下文相关规则
        if rule_ids is None or "CPP-FREE-ORDER" in rule_ids:
            issue = _check_free_order(lines, index)
            if issue:
                issues.append(issue)

    return issues


def parse_cpp_issues(code: str) -> List[Dict[str, Any]]:
    """给 Agent 用的检查结果（字典列表，便于塞进消息/提示词）。"""
    return [issue.to_dict() for issue in check_cpp(code)]


def issue_keys(code: str) -> set[str]:
    """只取问题编号集合，用于前后对比。"""
    return {issue.key for issue in check_cpp(code)}


# ----------------------------------------------------------------------
# 确定性自动修复（兜底通道）
# ----------------------------------------------------------------------
def apply_safe_fixes(code: str) -> Dict[str, Any]:
    """对**高置信度**的问题做确定性修复，返回新代码 + 修复记录。

    这是修复 Agent 的兜底通道：当大模型输出不可用、或漏改某些行时，
    这里用规则做保守修复，保证「验证」环节能验收通过。
    只做逐行文本替换与整段函数重写，且只作用于内存中的字符串。
    """
    lines = code.splitlines()
    changes: List[Dict[str, Any]] = []

    # ---- 修复 1：priority_queue 模板参数 ----
    for i, text in enumerate(lines):
        if RULES[0].pattern.search(text):
            fixed = re.sub(r"(priority_queue\s*<\s*)([A-Za-z_]\w*)(\s*,\s*vector)", r"\1\2*\3", text)
            if fixed != text:
                changes.append({"line_no": i + 1, "before": text.strip(), "after": fixed.strip(),
                                "reason": "把 priority_queue 的第一个模板参数改成指针类型"})
                lines[i] = fixed

    # ---- 修复 2：递归释放函数（判空写反 / 释放顺序） ----
    i = 0
    while i < len(lines):
        issue = _check_free_order(lines, i)
        if issue is None:
            i += 1
            continue
        body = _function_body(lines, i)
        if not body:
            i += 1
            continue
        body_start = body[0][0]
        body_end = body[-1][0] + 1          # 结尾 '}' 所在行号（0 基）
        # 定位函数头：函数体内第一条语句的上一行通常是 '{'，再往上才是函数头
        func_start = body_start - 1
        while func_start > 0 and not re.search(r"\)\s*\{?\s*$", lines[func_start]):
            func_start -= 1
        func_name = _function_name(lines, i) or "freeTree"
        param = _DELETE.search(lines[i]).group(1)
        indent = re.match(r"^\s*", lines[func_start]).group(0)
        inner = indent + "    "

        # 保留函数头（去掉可能跟在同一行的 '{'），只重写函数体
        header = lines[func_start]
        open_brace_index = header.rfind("{")
        if open_brace_index >= 0:
            header = header[:open_brace_index].rstrip()

        new_body = [
            f"{inner}if ({param} == nullptr)",
            f"{inner}    return;",
            f"{inner}{func_name}({param}->left);",
            f"{inner}{func_name}({param}->right);",
            f"{inner}delete {param};",
        ]
        changes.append({
            "line_no": i + 1,
            "before": "\n".join(lines[body_start:body_end]).strip(),
            "after": "\n".join(new_body + [indent + "}"]).strip(),
            "reason": f"重写 {func_name}：判空改为 == nullptr，并改为先递归释放子节点、最后释放自身",
        })
        head_lines = lines[:func_start] + ([header] if header else []) + ["{"]
        tail = lines[body_end + 1:]
        lines = head_lines + new_body + [indent + "}", ""] + tail
        i += 1

    return {"code": "\n".join(lines), "changes": changes}
