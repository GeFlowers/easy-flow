"""提供 DeerFlow 工具模块的延迟导入入口。"""

from .tools import get_available_tools

__all__ = ["get_available_tools", "skill_manage_tool"]


def __getattr__(name: str):
    """按需导入公开工具，避免包初始化时加载重量级依赖。"""
    if name == "skill_manage_tool":
        from .skill_manage_tool import skill_manage_tool

        return skill_manage_tool
    raise AttributeError(name)
