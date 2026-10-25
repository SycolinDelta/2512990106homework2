"""tools —— 确定性工具。

这里的工具不依赖大模型，输入输出完全确定，用来：
1. 读取代码文件（只读，绝不修改源文件）；
2. 对 C++ 代码做静态检查，给 Agent 的审查/验证提供客观依据。
"""

from tools.file_reader import read_code_file
from tools.cpp_static_checker import check_cpp, parse_cpp_issues, apply_safe_fixes

__all__ = [
    "read_code_file",
    "check_cpp",
    "parse_cpp_issues",
    "apply_safe_fixes",
]
