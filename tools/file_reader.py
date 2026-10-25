"""只读文件读取工具。

行为与 Homework1 的 read_code_file 保持一致：依次尝试 UTF-8 / GBK / latin-1，
对各种异常返回明确的错误字符串，不抛异常、不修改源文件。
"""

from __future__ import annotations

import os


def read_code_file(file_path: str) -> str:
    """读取本地代码文件，返回「文件读取成功(编码:xxx):\\n内容」格式的字符串。

    失败时返回以「错误：」开头的说明字符串。
    """
    try:
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                with open(file_path, "r", encoding=enc) as f:
                    content = f.read()
                return f"文件读取成功(编码:{enc}):\n{content}"
            except UnicodeDecodeError:
                continue
        return f"错误：无法识别文件编码 {file_path}"
    except FileNotFoundError:
        return f"错误：找不到文件 {file_path}"
    except IsADirectoryError:
        return f"错误：{file_path} 是一个文件夹，不是文件"
    except PermissionError:
        return f"错误：没有权限读取文件 {file_path}"
    except Exception as e:  # noqa: BLE001
        return f"读取文件异常：{e}"


def looks_like_file_path(text: str, extensions: set[str]) -> bool:
    """判断单行输入是否以常见代码文件后缀结尾（视为文件路径）。"""
    t = text.strip()
    if "\n" in t:  # 多行输入不强制识别，交给 LLM 自主判断
        return False
    return any(t.lower().endswith(ext) for ext in extensions)


def detect_language(file_path: str) -> str:
    """根据文件后缀判断语言，目前主要区分 cpp 和非 cpp。"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hxx"}:
        return "cpp"
    return "other"
