'''在运行时搜索并发现延迟加载的工具。

本模块构建不可变的延迟工具目录、搜索工具和路由中间件。代理先看到工具名称，
再通过搜索工具取得完整模式；提升状态保存在每个线程的图状态中。
'''

import hashlib
import html
import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Annotated, Any

from langchain.tools import BaseTool
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langchain_core.utils.function_calling import convert_to_openai_function
from langgraph.types import Command

from deerflow.tools.mcp_metadata import get_mcp_routing, is_mcp_tool

if TYPE_CHECKING:
    from langchain.agents.middleware import AgentMiddleware

logger = logging.getLogger(__name__)

MAX_RESULTS = 5


def _compile_catalog_regex(pattern: str) -> re.Pattern[str]:
    '''不区分大小写地编译模式；无效模式退化为字面量匹配而不抛出异常。'''
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(pattern), re.IGNORECASE)




@dataclass(frozen=True)
class DeferredToolCatalog:
    '''不可变的延迟工具目录，仅提供无副作用的搜索。'''

    tools: tuple[BaseTool, ...]

    @cached_property
    def names(self) -> frozenset[str]:
        '''返回目录中全部工具名称的不可变集合。'''
        return frozenset(t.name for t in self.tools)

    @cached_property
    def hash(self) -> str:
        '''返回由目录工具模式计算出的稳定短哈希。'''
        canon = [{"name": t.name, "schema": convert_to_openai_function(t)} for t in sorted(self.tools, key=lambda t: t.name)]
        blob = json.dumps(canon, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def search(self, query: str) -> list[BaseTool]:
        '''按照查询语法返回匹配的延迟工具。'''
        query = query.strip()
        if not query:
            return []

        if query.startswith("select:"):
            wanted = {n.strip() for n in query[7:].split(",")}
            return [t for t in self.tools if t.name in wanted]

        if query.startswith("+"):
            parts = query[1:].split(None, 1)
            if not parts:
                return []
            required = parts[0].lower()
            candidates = [t for t in self.tools if required in t.name.lower()]
            if len(parts) > 1:
                candidates.sort(key=lambda t: _catalog_regex_score(parts[1], t), reverse=True)
            return candidates[:MAX_RESULTS]

        regex = _compile_catalog_regex(query)
        scored: list[tuple[int, BaseTool]] = []
        for t in self.tools:
            searchable = f"{t.name} {t.description or ''}"
            if regex.search(searchable):
                scored.append((2 if regex.search(t.name) else 1, t))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored][:MAX_RESULTS]


def _catalog_regex_score(pattern: str, t: BaseTool) -> int:
    '''计算模式在工具名称及描述中的匹配次数。'''
    regex = _compile_catalog_regex(pattern)
    return len(regex.findall(f"{t.name} {t.description or ''}"))




@dataclass(frozen=True)
class DeferredToolSetup:
    '''一次代理构建所需的延迟工具配置。

    三个字段必须保持一致：没有搜索工具时，延迟名称集合为空且目录哈希为空。
    '''

    tool_search_tool: BaseTool | None
    deferred_names: frozenset[str]
    catalog_hash: str | None


def build_tool_search_tool(catalog: DeferredToolCatalog) -> BaseTool:
    '''基于延迟工具目录构建工具搜索工具。'''
    catalog_hash = catalog.hash

    @tool
    def tool_search(query: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
        '''取得延迟工具的完整模式定义，使其可以被调用。

        支持按确切名称选择、按关键字搜索，以及以加号开头的名称限定搜索。
        '''
        matched = catalog.search(query)
        if not matched:
            content, names = f"No tools found matching: {query}", []
        else:
            content = json.dumps([convert_to_openai_function(t) for t in matched], indent=2, ensure_ascii=False)
            names = [t.name for t in matched]
        return Command(
            update={
                "promoted": {"catalog_hash": catalog_hash, "names": names},
                "messages": [ToolMessage(content=content, tool_call_id=tool_call_id, name="tool_search")],
            }
        )

    return tool_search


def build_deferred_tool_setup(filtered_tools: list[BaseTool], *, enabled: bool) -> DeferredToolSetup:
    '''从已通过策略过滤的工具列表构建延迟工具配置。

    必须在策略过滤后调用，确保目录不会暴露当前代理无权使用的工具。
    '''
    if not enabled:
        return DeferredToolSetup(None, frozenset(), None)
    deferred = [t for t in filtered_tools if is_mcp_tool(t)]
    if not deferred:
        return DeferredToolSetup(None, frozenset(), None)
    catalog = DeferredToolCatalog(tuple(deferred))
    return DeferredToolSetup(build_tool_search_tool(catalog), catalog.names, catalog.hash)


def assemble_deferred_tools(filtered_tools: list[BaseTool], *, enabled: bool) -> tuple[list[BaseTool], DeferredToolSetup]:
    '''从已通过策略过滤的列表构建最终工具列表及延迟工具配置。

    若启用延迟加载但无法恢复应延迟的 MCP 工具集合，则拒绝绑定其模式。
    '''
    deferred_setup = build_deferred_tool_setup(filtered_tools, enabled=enabled)
    if enabled and not deferred_setup.deferred_names and any(is_mcp_tool(t) for t in filtered_tools):
        raise RuntimeError("tool_search enabled and MCP tools survived policy filtering, but no deferred set was recovered - refusing to bind MCP schemas (fail-closed).")
    final_tools = list(filtered_tools)
    if deferred_setup.tool_search_tool:
        final_tools.append(deferred_setup.tool_search_tool)
    return final_tools, deferred_setup


def _routing_priority(value: Any) -> int:
    '''将路由优先级安全转换为整数。'''
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _routing_keywords(value: Any) -> list[str]:
    '''将路由关键字安全规范化为字符串列表。'''
    if not isinstance(value, list):
        return []
    return [keyword for keyword in (str(item).strip() for item in value) if keyword]


def build_mcp_routing_middleware(
    tools: Iterable[BaseTool],
    deferred_setup: DeferredToolSetup,
    *,
    top_k: int,
) -> "AgentMiddleware | None":
    '''从已通过策略过滤的延迟工具构建自动提升路由中间件。

    构建时可读取工具元数据，返回的中间件只接收可序列化的扁平路由索引。
    '''
    if deferred_setup.catalog_hash is None or not deferred_setup.deferred_names:
        return None

    routing_index: dict[str, dict[str, Any]] = {}
    for candidate in tools:
        tool_name = getattr(candidate, "name", "")
        if tool_name not in deferred_setup.deferred_names:
            continue
        routing = get_mcp_routing(candidate)
        if routing is None or routing.get("mode") != "prefer":
            continue
        keywords = _routing_keywords(routing.get("keywords"))
        if not keywords:
            continue
        if routing.get("auto_promote_top_k") is not None:
            logger.debug("Ignoring per-tool MCP routing auto_promote_top_k for %s in PR2", tool_name)
        routing_index[str(tool_name)] = {
            "priority": _routing_priority(routing.get("priority", 0)),
            "keywords": keywords,
        }

    if not routing_index:
        return None

    from deerflow.agents.middlewares.mcp_routing_middleware import McpRoutingMiddleware

    return McpRoutingMiddleware(routing_index, deferred_setup.catalog_hash, top_k)




def get_deferred_tools_prompt_section(*, deferred_names: frozenset[str] = frozenset()) -> str:
    '''根据明确的延迟工具名称集合生成可用工具提示区段。

    仅列出名称；没有延迟工具时返回空字符串，名称会在输出前进行转义。
    '''
    if not deferred_names:
        return ""
    names = "\n".join(html.escape(name, quote=False) for name in sorted(deferred_names))
    return f"<available-deferred-tools>\n{names}\n</available-deferred-tools>"


def _format_keyword_list(keywords: list[str]) -> str:
    '''将关键字列表格式化为自然语言短语。'''
    if len(keywords) == 1:
        return keywords[0]
    return f"{', '.join(keywords[:-1])}, or {keywords[-1]}"


def get_mcp_routing_hints_prompt_section(tools: Iterable[BaseTool], *, deferred_names: frozenset[str] = frozenset()) -> str:
    '''从携带路由元数据的 MCP 工具渲染路由提示区段。

    已延迟的工具会提示代理先提升工具，再尝试调用其模式。
    '''
    hints: list[tuple[int, str, list[str]]] = []
    for candidate in tools:
        routing = get_mcp_routing(candidate)
        if routing is None or routing.get("mode") != "prefer":
            continue
        keywords = routing.get("keywords") or []
        if not keywords:
            continue
        hints.append((int(routing.get("priority", 0)), candidate.name, [html.escape(str(keyword), quote=False) for keyword in keywords]))

    if not hints:
        return ""

    lines = ["<mcp_routing_hints>"]
    for priority, tool_name, keywords in sorted(hints, key=lambda item: (-item[0], item[1])):
        esc_name = html.escape(tool_name, quote=False)
        lines.append(f"When the user's request involves {_format_keyword_list(keywords)}:")
        if tool_name in deferred_names:
            lines.append(f"  use `tool_search` to fetch `{esc_name}`, then prefer that MCP tool.")
        else:
            lines.append(f"  prefer the `{esc_name}` tool.")
    lines.append("</mcp_routing_hints>")
    return "\n".join(lines)
