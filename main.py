"""Homework2 主程序：Simple Workflow MVP（代码审查流程）。

与 Homework1 完全相同的交互方式：
    - 启动后直接输入：可以贴一个代码文件路径，也可以直接粘贴代码；
    - 多行输入，单独输入一行 END 结束录入；输入 exit 退出程序；
    - 一次只处理一个文件；出错不会退出程序，可以继续输入。

区别只在输出：
    Homework1 → 修改建议 + 加注释的代码；
    Homework2 → 多个 Agent 协作自行修复后的**结果**（修复概览 / 修复后代码 / 验证结论）。

用法：
    python main.py                    # 交互模式（使用 .env 中配置的大模型）
    python main.py --file test.cpp    # 直接审查一个文件（一次性）
    python main.py --graph            # 打印 Workflow 流程图（文字 + mermaid）
    python main.py --log run.json     # 把执行日志写到文件
    python main.py --max-rounds 3     # 审查-修复循环上限（默认 3）
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from dotenv import load_dotenv

from agents.base import LLMClient
from agents.coder import CoderAgent
from agents.fixer import FixerAgent
from agents.reviewer import ReviewerAgent
from agents.tester import TesterAgent
from output import render_result
from tools.file_reader import looks_like_file_path
from workflow.graph import build_default_graph
from workflow.orchestrator import run_workflow
from workflow.state import WorkflowState

# 加载环境变量，把你的 api key 写在 .env 文件
load_dotenv()

# 常见代码/文本文件后缀，用于前端强制识别文件路径（与 Homework1 一致）
CODE_EXTENSIONS = {
    ".py", ".pyw", ".js", ".ts", ".jsx", ".html", ".css", ".vue", ".java",
    ".c", ".cpp", ".h", ".hpp", ".go", ".rs", ".rb", ".php", ".txt", ".md",
    ".json", ".csv", ".xml", ".yml", ".yaml", ".sh", ".bat", ".sql",
}


# ----------------------------------------------------------------------
# 组装 Workflow
# ----------------------------------------------------------------------
def build_pipeline(max_rounds: int = 3, verbose: bool = False):
    """创建四个 Agent，并组装成 WorkflowGraph。"""
    llm = LLMClient(temperature=0.2)

    coder = CoderAgent(llm)
    reviewer = ReviewerAgent(llm)
    fixer = FixerAgent(llm)
    tester = TesterAgent(llm)

    graph = build_default_graph(coder, reviewer, fixer, tester, max_rounds=max_rounds)

    def on_event(message: str) -> None:
        if verbose:
            print(f"  {message}", flush=True)

    return graph, on_event


# ----------------------------------------------------------------------
# 单次运行
# ----------------------------------------------------------------------
def run_once(user_input: str, graph, on_event,
             log_path: Optional[str] = None) -> str:
    """对一次输入运行 Workflow，返回格式化后的结果文本。"""
    source_name = "<input>"
    language = "other"
    # 前端确定性识别：单行且以代码后缀结尾 => 当作文件路径
    if looks_like_file_path(user_input, CODE_EXTENSIONS):
        source_name = user_input.strip()
        from tools.file_reader import detect_language
        language = detect_language(source_name)
        if not os.path.isfile(source_name):
            return (f"错误：找不到文件 {source_name}\n"
                    "（HomeWork2 只读取文件，不会修改源文件；请确认路径后重新输入）")

    state = WorkflowState(raw_input=user_input, source_name=source_name, language=language)
    try:
        run_workflow(graph, state, retry=1, on_event=on_event)
    except Exception as err:  # noqa: BLE001 —— 兜底：任何异常都不让程序退出
        state.error = f"{type(err).__name__}: {err}"
        state.stop_reason = "error"
        state.finished = True

    if log_path:
        state.to_json(log_path)

    # 没有可用的大模型（未配置 Key / 未安装依赖 / 调用失败）时给出明确提示
    if state.review is None and state.error:
        hint = ""
        if "LLM" in state.error or "api" in state.error.lower() or "langchain" in state.error.lower():
            hint = ("\n提示：大模型不可用。请检查 .env 中的 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL，"
                    "并确认已执行 pip install -r requirements.txt。")
        return f"运行出错：{state.error}{hint}"

    return render_result(state)


# ----------------------------------------------------------------------
# 交互入口（与 Homework1 完全一致）
# ----------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Homework2：代码审查 Workflow（修复并验证）")
    parser.add_argument("--file", help="直接审查指定文件（一次性运行）")
    parser.add_argument("--graph", action="store_true", help="打印 Workflow 流程图")
    parser.add_argument("--log", help="把执行日志（含消息记录）写到指定 JSON 文件")
    parser.add_argument("--max-rounds", type=int, default=3, help="审查-修复循环上限，默认 3")
    parser.add_argument("--verbose", action="store_true", help="实时打印各节点执行进度")
    args = parser.parse_args()

    verbose = args.verbose or os.getenv("H2_VERBOSE") == "1"
    graph, on_event = build_pipeline(max_rounds=args.max_rounds, verbose=verbose)

    # ---- 只打印流程图 ----
    if args.graph:
        print(graph.describe())
        print("\n--- mermaid ---\n" + graph.to_mermaid())
        return

    # ---- 一次性处理一个文件 ----
    if args.file:
        print(run_once(args.file, graph, on_event, log_path=args.log))
        return

    # ---- 交互模式（与 Homework1 相同的提示与循环） ----
    print("===== 代码审查 Workflow（多 Agent：审查 → 修复 → 验证） =====")
    print(f"当前大模型：{os.getenv('LLM_MODEL', '未配置')}")
    print("使用说明：提交一个代码文件的路径（支持多种后缀名），或者直接输入代码；")
    print("注意：请勿一次输入多个文件路径，需要审查多个文件时请逐个提交；")
    print("输入完成后单独输入一行 END 并回车以结束录入；输入 exit 退出程序。")
    print("说明：本程序只读取代码文件，不会修改源文件；修复结果只输出到终端。")

    while True:
        print("\n>>> 请输入：")
        # 多行读取：input() 不带提示符，光标自动换到新行等待输入
        lines = []
        try:
            while True:
                line = input()
                if line.strip().lower() == "exit":
                    print("程序退出。")
                    return
                if line.strip() == "END":
                    break
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            print("\n程序退出。")
            return

        user_input = "\n".join(lines).strip()
        if not user_input:
            print("输入为空，请重新输入。")
            continue

        try:
            # 多行输入里若包含多个文件路径，提示用户逐个提交
            path_lines = [l for l in user_input.splitlines()
                          if looks_like_file_path(l, CODE_EXTENSIONS)]
            if len(path_lines) > 1:
                print("检测到多个文件路径，请一次只提交一个文件，请逐个输入。")
                continue

            print("\n【Workflow 执行中】")
            print(run_once(user_input, graph, on_event, log_path=args.log))
        except Exception as err:  # noqa: BLE001 —— 与 Homework1 一样：出错不退出
            print(f"\n运行出错：{err}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n程序退出。")
        sys.exit(0)
