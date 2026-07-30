"""定义工具驱动记忆模式供模型直接调用的记忆工具。

当 ``memory.mode == "tool"`` 时，代理注册搜索、新增、更新和删除记忆工具，
而不添加 ``MemoryMiddleware``；模型据此自行决定记住、检索、更新或删除过期
事实的时机。工具经由 ``MemoryManager`` 抽象访问；后端缺少可选写入能力时返回
包含 ``error`` 的结构化结果，而不会崩溃。
"""

import json
import logging

from langchain.tools import tool

from deerflow.agents.memory.manager import get_memory_manager
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)


def _resolve_scope(runtime: Runtime | None = None) -> tuple[str | None, str]:
    """解析记忆工具处理器所需的代理名和用户标识范围。

    工具执行优先从图运行时上下文取得元数据，以确保跨请求和任务边界的
    持久化范围正确。
    """
    context = getattr(runtime, "context", None)
    agent_name = None
    if isinstance(context, dict) and context.get("agent_name"):
        agent_name = str(context["agent_name"])
    return agent_name, resolve_runtime_user_id(runtime)


def _memory_content_key(content: str) -> str:
    """生成忽略首尾空白与大小写的记忆内容去重键。"""
    return content.strip().casefold()


@tool("memory_search", parse_docstring=True)
def memory_search_tool(
    runtime: Runtime,
    query: str,
    category: str | None = None,
    limit: int = 10,
) -> str:
    """按自然语言查询检索已有事实。

    用于了解已记录的用户偏好、既往纠正、上下文或其他事实。``query`` 与事实
    内容进行不区分大小写的子串匹配；``category`` 可限定类别；``limit`` 指定
    最多返回数量。结果为含 ``results`` 与 ``count`` 的结构化字符串。
    """
    agent_name, user_id = _resolve_scope(runtime)
    try:
        results = get_memory_manager().search(
            query,
            top_k=limit,
            user_id=user_id,
            agent_name=agent_name,
            category=category,
        )
        return json.dumps({"results": results, "count": len(results)}, ensure_ascii=False)
    except Exception as exc:
        logger.exception("memory_search_tool failed")
        return json.dumps({"error": str(exc)})


@tool("memory_add", parse_docstring=True)
def memory_add_tool(
    runtime: Runtime,
    content: str,
    category: str = "context",
    confidence: float = 0.7,
) -> str:
    """保存关于用户或会话上下文的新事实。

    用户提供值得在后续会话记住的偏好、纠正、个人信息或工作上下文时使用。事实
    跨会话持久保存，可供检索和自动上下文注入。``content`` 应具体且符合事实；
    ``category`` 为分类标签；``confidence`` 是零到一之间的置信度。结果为含
    ``fact_id`` 和 ``status`` 的结构化字符串，内容重复时返回 ``error``。
    """
    agent_name, user_id = _resolve_scope(runtime)
    try:
        normalized_content = content.strip()
        if not normalized_content:
            return json.dumps({"error": "empty content"})
        content_key = _memory_content_key(normalized_content)
        manager = get_memory_manager()
        existing_facts = manager.get_memory(agent_name=agent_name, user_id=user_id).get("facts", [])
        # Tool calls normally run one-at-a-time per user turn. If tool-mode
        # writing broadens to multiple concurrent calls for the same user,
        # move duplicate rejection into the storage/update critical section.
        if any(_memory_content_key(str(fact.get("content", ""))) == content_key for fact in existing_facts):
            return json.dumps({"error": "Duplicate fact"})

        create = getattr(manager, "create_fact", None)
        if not callable(create):
            return json.dumps({"error": f"memory backend {type(manager).__name__} does not support create_fact"})
        # create_fact returns (memory_data, fact_id) -- use the id directly rather
        # than re-deriving it by content matching (which would couple the tool to
        # the backend's content normalization and could misreport a storage cap).
        _memory_data, fact_id = create(
            normalized_content,
            category=category,
            confidence=confidence,
            agent_name=agent_name,
            user_id=user_id,
        )
        if fact_id is None:
            # max_facts cap kept higher-confidence facts and evicted the new one;
            # the fact was not stored -- report honestly instead of a dangling id.
            return json.dumps({"error": "Fact was not stored because memory.max_facts kept higher-confidence facts"})
        return json.dumps({"fact_id": fact_id, "status": "added"})
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        logger.exception("memory_add_tool failed")
        return json.dumps({"error": str(exc)})


# Tool mode exposes explicit CRUD, not the passive staleness-review path.
# The staleness age/category/removal-count guardrails protect automatic
# middleware cleanup; tool-mode operators opt into model-directed updates
# and deletes. The docs call out this difference for configuration review.


@tool("memory_update", parse_docstring=True)
def memory_update_tool(
    runtime: Runtime,
    fact_id: str,
    content: str | None = None,
    category: str | None = None,
    confidence: float | None = None,
) -> str:
    """更新已有事实，仅修改实际提供的字段。

    当事实已过期、不正确或需细化时，先检索得到 ``fact_id`` 再调用此工具。
    ``content``、``category`` 和 ``confidence`` 未提供时保持原值；结果为含
    ``fact_id`` 和 ``status`` 的结构化字符串，无效标识时返回 ``error``。
    """
    agent_name, user_id = _resolve_scope(runtime)
    try:
        manager = get_memory_manager()
        update = getattr(manager, "update_fact", None)
        if not callable(update):
            return json.dumps({"error": f"memory backend {type(manager).__name__} does not support update_fact"})
        update(
            fact_id,
            content=content,
            category=category,
            confidence=confidence,
            agent_name=agent_name,
            user_id=user_id,
        )
        return json.dumps({"fact_id": fact_id, "status": "updated"})
    except KeyError:
        return json.dumps({"error": f"Fact not found: {fact_id}"})
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        logger.exception("memory_update_tool failed")
        return json.dumps({"error": str(exc)})


@tool("memory_delete", parse_docstring=True)
def memory_delete_tool(runtime: Runtime, fact_id: str) -> str:
    """按标识删除不再准确或相关的事实。

    应先检索得到 ``fact_id`` 再删除。结果为含 ``fact_id`` 和 ``status`` 的结构化字符串，
    无效标识时返回 ``error``。
    """
    agent_name, user_id = _resolve_scope(runtime)
    try:
        manager = get_memory_manager()
        delete = getattr(manager, "delete_fact", None)
        if not callable(delete):
            return json.dumps({"error": f"memory backend {type(manager).__name__} does not support delete_fact"})
        delete(fact_id, agent_name=agent_name, user_id=user_id)
        return json.dumps({"fact_id": fact_id, "status": "deleted"})
    except KeyError:
        return json.dumps({"error": f"Fact not found: {fact_id}"})
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        logger.exception("memory_delete_tool failed")
        return json.dumps({"error": str(exc)})


def get_memory_tools() -> list:
    """返回用于代理注册的全部记忆工具。

    代理工厂在 ``memory.mode == "tool"`` 时调用此函数。
    """
    return [
        memory_search_tool,
        memory_add_tool,
        memory_update_tool,
        memory_delete_tool,
    ]
