#!/usr/bin/env python3
"""系统性文献综述技能使用的 arXiv 检索客户端。

模块查询公开的预印本平台接口并以 JSON 返回结构化论文元数据，无需接口密钥。它只承担
文献检索与 Atom 结果解析：可用时使用 ``requests``，否则以兼容接口回退到 ``urllib``；
查询参数以 URL 编码保证多词主题正确传递，显式命名空间避免 Atom 解析错误，并将完整论文
链接规范化为裸 arXiv 标识。``max_results`` 会限制为 50，超大规模综述不在此技能范围内。
本模块不扫描技能包，也不修改部署或运行时配置。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# Namespace map for arXiv's Atom feed. arXiv extends Atom with its own
# elements (primary_category, comment, journal_ref) under the `arxiv:`
# prefix; the core entry fields live under `atom:`.
NS_MAP = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

ARXIV_ENDPOINT = "http://export.arxiv.org/api/query"
MAX_RESULTS_UPPER_BOUND = 50
DEFAULT_TIMEOUT_SECONDS = 30


# --- HTTP client with requests -> urllib fallback --------------------------

try:
    import requests  # type: ignore
except ImportError:
    import urllib.error
    import urllib.parse
    import urllib.request

    class _UrllibResponse:
        """保存 ``urllib`` 响应，使其具备调用方所需的 ``requests`` 属性。"""

        def __init__(self, data: bytes, status: int) -> None:
            """保存原始字节、状态码、UTF-8 文本和二进制内容。"""
            self._data = data
            self.status_code = status
            self.text = data.decode("utf-8", errors="replace")
            self.content = data

        def raise_for_status(self) -> None:
            """当 HTTP 状态码为失败状态时抛出运行时异常。"""
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class _UrllibRequestsShim:
        """以 ``urllib`` 实现 arXiv 检索所需的最小 ``requests`` 兼容接口。"""

        @staticmethod
        def get(
            url: str,
            params: dict | None = None,
            timeout: int = DEFAULT_TIMEOUT_SECONDS,
        ) -> _UrllibResponse:
            """编码查询参数后执行 GET 请求，并包装成功或 HTTP 错误响应。"""
            if params:
                query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote_plus)
                url = f"{url}?{query}"
            req = urllib.request.Request(url, headers={"User-Agent": "deerflow-slr-skill/0.1"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return _UrllibResponse(resp.read(), resp.status)
            except urllib.error.HTTPError as e:
                return _UrllibResponse(e.read(), e.code)

    requests = _UrllibRequestsShim()  # type: ignore


# --- Core query + parsing --------------------------------------------------


def _build_search_query(
    query: str,
    category: str | None,
    start_date: str | None,
    end_date: str | None,
) -> str:
    """构造预印本平台的 ``search_query`` 字段，组合主题、分类和提交日期范围。

    该平台使用 ``ti:``、``abs:``、``cat:``、``all:`` 与布尔组合符的专用查询语法；
    本函数以 ``all:`` 匹配主题的标题、摘要和作者，并按需附加分类及日期条件。
    """
    # Wrap multi-word queries in double quotes so arXiv's Lucene parser
    # treats them as a phrase.  Without quotes, `all:diffusion model` is
    # parsed as `all:diffusion OR model`, pulling in unrelated papers
    # that merely mention the word "model".
    if " " in query:
        parts = [f'all:"{query}"']
    else:
        parts = [f"all:{query}"]
    if category:
        parts.append(f"cat:{category}")
    if start_date or end_date:
        # arXiv date range format: [YYYYMMDDHHMM TO YYYYMMDDHHMM]
        lo = (start_date or "19910101").replace("-", "") + "0000"
        hi = (end_date or "29991231").replace("-", "") + "2359"
        parts.append(f"submittedDate:[{lo} TO {hi}]")
    return " AND ".join(parts)


def _normalise_arxiv_id(raw_id: str) -> str:
    """将完整 arXiv 链接转换为无版本号的裸标识，兼容新旧编号格式。"""
    # Extract everything after /abs/ to preserve legacy archive prefix
    if "/abs/" in raw_id:
        tail = raw_id.split("/abs/", 1)[1]
    else:
        tail = raw_id.rsplit("/", 1)[-1]
    # Strip version suffix: "1706.03762v5" -> "1706.03762"
    if "v" in tail:
        base, _, suffix = tail.rpartition("v")
        if suffix.isdigit():
            return base
    return tail


def _parse_entry(entry: Any) -> dict:
    """将单个 Atom ``entry`` 元素解析为包含论文元数据的字典。"""
    import xml.etree.ElementTree as ET

    def _text(path: str) -> str:
        """按命名空间路径读取元素文本；节点或文本缺失时返回空字符串。"""
        node = entry.find(path, NS_MAP)
        return (node.text or "").strip() if node is not None and node.text else ""

    raw_id = _text("atom:id")
    arxiv_id = _normalise_arxiv_id(raw_id)

    authors = [(a.findtext("atom:name", default="", namespaces=NS_MAP) or "").strip() for a in entry.findall("atom:author", NS_MAP)]
    authors = [a for a in authors if a]

    categories = [c.get("term", "") for c in entry.findall("atom:category", NS_MAP) if c.get("term")]

    pdf_url = ""
    abs_url = raw_id  # default
    for link in entry.findall("atom:link", NS_MAP):
        if link.get("title") == "pdf":
            pdf_url = link.get("href", "")
        elif link.get("rel") == "alternate":
            abs_url = link.get("href", abs_url)

    # Dates come as ISO 8601 (2017-06-12T17:57:34Z). Keep the date part.
    published_raw = _text("atom:published")
    updated_raw = _text("atom:updated")
    published = published_raw.split("T", 1)[0] if published_raw else ""
    updated = updated_raw.split("T", 1)[0] if updated_raw else ""

    # Abstract (<summary>) has ragged whitespace from arXiv's formatting.
    # Collapse internal whitespace to make downstream LLM consumption easier.
    abstract = " ".join(_text("atom:summary").split())

    # Silence unused import warning; ET is only needed for type hints above.
    del ET

    return {
        "id": arxiv_id,
        "title": " ".join(_text("atom:title").split()),
        "authors": authors,
        "abstract": abstract,
        "published": published,
        "updated": updated,
        "categories": categories,
        "pdf_url": pdf_url,
        "abs_url": abs_url,
    }


def search(
    query: str,
    max_results: int = 20,
    category: str | None = None,
    sort_by: str = "relevance",
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """检索预印本平台并返回论文词典列表。

    主题可为自由文本；结果数会限制为 50，分类、排序字段与起止日期均为可选过滤条件。
    每个结果词典遵循该技能 ``SKILL.md`` 中定义的论文元数据结构。
    """
    import xml.etree.ElementTree as ET

    if max_results <= 0:
        return []
    max_results = min(max_results, MAX_RESULTS_UPPER_BOUND)

    search_query = _build_search_query(query, category, start_date, end_date)
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": "descending",
    }

    resp = requests.get(ARXIV_ENDPOINT, params=params, timeout=DEFAULT_TIMEOUT_SECONDS)
    resp.raise_for_status()

    # arXiv returns Atom XML, not JSON.
    root = ET.fromstring(resp.text)
    entries = root.findall("atom:entry", NS_MAP)
    return [_parse_entry(e) for e in entries]


# --- CLI -------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """创建文献检索命令行参数解析器，不执行检索请求。"""
    parser = argparse.ArgumentParser(
        description="Query the arXiv API and emit structured paper metadata as JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python arxiv_search.py "transformer attention" --max-results 10\n'
            '  python arxiv_search.py "diffusion models" --category cs.CV --sort-by submittedDate\n'
            '  python arxiv_search.py "graph neural networks" --start-date 2023-01-01\n'
        ),
    )
    parser.add_argument("query", help="free-text search topic")
    parser.add_argument(
        "--max-results",
        type=int,
        default=20,
        help=f"number of papers to return (default: 20, max: {MAX_RESULTS_UPPER_BOUND})",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="optional arXiv category filter, e.g. cs.CL, cs.CV, stat.ML",
    )
    parser.add_argument(
        "--sort-by",
        default="relevance",
        choices=["relevance", "submittedDate", "lastUpdatedDate"],
        help="sort order (default: relevance)",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="earliest submission date, YYYY-MM-DD (inclusive)",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="latest submission date, YYYY-MM-DD (inclusive)",
    )
    return parser


def main() -> int:
    """执行命令行文献检索，将结果以 UTF-8 JSON 写入标准输出。"""
    args = _build_parser().parse_args()
    try:
        papers = search(
            query=args.query,
            max_results=args.max_results,
            category=args.category,
            sort_by=args.sort_by,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    except Exception as exc:
        print(f"arxiv_search.py: {exc}", file=sys.stderr)
        return 1

    json.dump(papers, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
