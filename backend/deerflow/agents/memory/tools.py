'''定义工具驱动记忆模式供模型直接调用的记忆工具。

当 ``memory.mode == "tool"`` 时，代理注册搜索、新增、更新和删除记忆工具，
而不添加 ``MemoryMiddleware``；模型据此自行决定记住、检索、更新或删除过期
事实的时机。工具经由 ``MemoryManager`` 抽象访问；后端缺少可选写入能力时返回
包含 ``error`` 的结构化结果，而不会崩溃。
'''

import json
import logging

from langchain.tools import tool

from deerflow.agents.memory.manager import get_memory_manager
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)


def _resolve_scope(runtime: Runtime | None = None) -> tuple[str | None, str]:
    '''解析记忆工具处理器所需的代理名和用户标识范围。

    工具执行优先从图运行时上下文取得元数据，以确保跨请求和任务边界的
    持久化范围正确。
    '''
    context = getattr(runtime, "context", None)
    agent_name = None
    if isinstance(context, dict) and context.get("agent_name"):
        agent_name = str(context["agent_name"])
    return agent_name, resolve_runtime_user_id(runtime)


def _memory_content_key(content: str) -> str:
    '''生成忽略首尾空白与大小写的记忆内容去重键。'''
    return content.strip().casefold()


@tool("memory_search", parse_docstring=True)
def memory_search_tool(
    runtime: Runtime,
    query: str,
    category: str | None = None,
    limit: int = 10,
) -> str:
    '''按自然语言查询已保存的用户或对话事实。

    需要查看已知的用户偏好、先前纠正、上下文或其他已保存事实时使用此工具。

    Args:
        query: 用于匹配事实内容的自然语言查询，按子字符串匹配且忽略大小写。
        category: 可选类别过滤条件，例如 "preference"、"correction"、
            "context"；仅返回类别完全相同的事实。
        limit: 返回结果的最大数量，默认为 10。

    Returns:
        包含 "results"（事实对象列表）和 "count" 的 JSON 字符串。
        每条事实包含 id、content、category、confidence、createdAt 和 source。
    '''
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
    '''将适合后续对话复用的新事实写入长期记忆。

    用户分享适合在后续对话中记住的偏好、纠正、个人细节或工作背景时使用此工具。
    事实会跨会话持久保存，可通过 memory_search 和自动上下文注入获取。

    Args:
        content: 要记住的事实文本，应具体且符合事实。
        category: 用于组织事实的类别标签，默认为 "context"，
            例如 "preference"、"correction"、"behavior"、"personal"。
        confidence: 对事实的确信程度，范围为 0.0-1.0，默认为 0.7。
            用户明确陈述的事实应取较高值，推断所得的事实应取较低值。

    Returns:
        包含 "fact_id" 和 "status": "added" 的 JSON 字符串。
        内容重复时返回 "error" 及原因说明。
    '''
    agent_name, user_id = _resolve_scope(runtime)
    try:
        normalized_content = content.strip()
        if not normalized_content:
            return json.dumps({"error": "empty content"})
        content_key = _memory_content_key(normalized_content)
        manager = get_memory_manager()
        existing_facts = manager.get_memory(agent_name=agent_name, user_id=user_id).get("facts", [])
        if any(_memory_content_key(str(fact.get("content", ""))) == content_key for fact in existing_facts):
            return json.dumps({"error": "Duplicate fact"})

        create = getattr(manager, "create_fact", None)
        if not callable(create):
            return json.dumps({"error": f"memory backend {type(manager).__name__} does not support create_fact"})
        _memory_data, fact_id = create(
            normalized_content,
            category=category,
            confidence=confidence,
            agent_name=agent_name,
            user_id=user_id,
        )
        if fact_id is None:
            return json.dumps({"error": "Fact was not stored because memory.max_facts kept higher-confidence facts"})
        return json.dumps({"fact_id": fact_id, "status": "added"})
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        logger.exception("memory_add_tool failed")
        return json.dumps({"error": str(exc)})




@tool("memory_update", parse_docstring=True)
def memory_update_tool(
    runtime: Runtime,
    fact_id: str,
    content: str | None = None,
    category: str | None = None,
    confidence: float | None = None,
) -> str:
    '''更新已保存事实中指定的字段，未提供的字段保持原值。

    已保存事实过时、错误或需要完善时使用此工具。
    先通过 memory_search 查找 fact_id，再更新对应事实。

    Args:
        fact_id: memory_search 结果中的事实标识，必填。
        content: 新事实文本，省略时保持原值。
        category: 新类别，省略时保持原值。
        confidence: 新置信度，范围为 0.0-1.0，省略时保持原值。

    Returns:
        包含 "fact_id" 和 "status": "updated" 的 JSON 字符串。
        fact_id 无效时返回 "error" 及原因说明。
    '''
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
    '''按事实 ID 删除一条长期记忆。

    事实不再准确或相关时使用此工具。先通过 memory_search 查找 fact_id，再删除该事实。

    Args:
        fact_id: 要删除的事实标识，来自 memory_search 结果。

    Returns:
        包含 "fact_id" 和 "status": "deleted" 的 JSON 字符串。
        fact_id 无效时返回 "error" 及原因说明。
    '''
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
    '''返回用于代理注册的全部记忆工具。

    代理工厂在 ``memory.mode == "tool"`` 时调用此函数。
    '''
    return [
        memory_search_tool,
        memory_add_tool,
        memory_update_tool,
        memory_delete_tool,
    ]
