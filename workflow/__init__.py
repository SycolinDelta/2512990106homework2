"""workflow —— 轻量 Workflow 编排层。

本包是本项目（Homework2）自己实现的编排引擎：不依赖 LangGraph 的状态图，
而是用「显式状态 + 显式消息 + 显式流程定义」把多个 Agent 编排成一条可复用的流水线。
"""

from workflow.graph import WorkflowGraph, build_default_graph
from workflow.message import Message
from workflow.state import WorkflowState

__all__ = ["Message", "WorkflowState", "WorkflowGraph", "build_default_graph"]
