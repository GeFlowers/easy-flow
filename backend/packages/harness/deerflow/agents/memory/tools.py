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
    """按自然语言查询已保存的用户或对话事实。

    Use this when you need to check what you already know about the user
    - their preferences, past corrections, context, or any stored facts.

    Args:
        query: Natural language query to match against fact content.
            Case-insensitive substring matching.
        category: Optional category filter (e.g. "preference", "correction",
            "context"). Only facts with this exact category are returned.
        limit: Maximum results to return (default 10).

    Returns:
        JSON string with "results" (list of fact objects) and "count".
        Each fact has id, content, category, confidence, createdAt, and source.
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
    """将适合后续对话复用的新事实写入长期记忆。

    Use this when the user shares something worth remembering for future
    conversations - preferences, corrections, personal details, work context.
    The fact persists across sessions and will be available via memory_search
    and automatic context injection.

    Args:
        content: The fact text to remember. Be specific and factual.
        category: Category label for organization (default "context").
            e.g. "preference", "correction", "behavior", "personal".
        confidence: How certain you are about this fact, 0.0-1.0
            (default 0.7). Use higher values for explicit user statements,
            lower for inferences.

    Returns:
        JSON string with "fact_id" and "status": "added".
        On duplicate content, returns "error" with explanation.
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
    """更新已保存事实中指定的字段，未提供的字段保持原值。

    Use this when a stored fact is outdated, incorrect, or needs refinement.
    First use memory_search to find the fact_id, then update it.

    Args:
        fact_id: Fact ID from memory_search results (required).
        content: New fact text (unchanged if omitted).
        category: New category (unchanged if omitted).
        confidence: New confidence score 0.0-1.0 (unchanged if omitted).

    Returns:
        JSON string with "fact_id" and "status": "updated".
        On invalid fact_id, returns "error" with explanation.
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
    """按事实 ID 删除一条长期记忆。

    Use this when a fact is no longer accurate or relevant. First use
    memory_search to find the fact_id, then delete it.

    Args:
        fact_id: Fact ID to delete (from memory_search results).

    Returns:
        JSON string with "fact_id" and "status": "deleted".
        On invalid fact_id, returns "error" with explanation.
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
