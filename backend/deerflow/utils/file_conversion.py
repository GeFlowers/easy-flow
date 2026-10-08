'''把上传的办公文档转换为 Markdown，并提取可供智能体浏览的文档大纲。'''

import asyncio
import logging
import re
from pathlib import Path

from deerflow.config.app_config import get_app_config

logger = logging.getLogger(__name__)

# 这些格式在上传后会转换为 Markdown，便于智能体读取内容。
CONVERTIBLE_EXTENSIONS = {
    ".pdf",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
}

# 大文件在线程池中转换，避免阻塞异步请求；小文件直接转换以减少调度开销。
_ASYNC_THRESHOLD_BYTES = 1 * 1024 * 1024  # 1 MB

# 若每页文本少于此阈值，通常意味着 PDF 是扫描件或受保护文档，应改用通用转换器；
# 无法取得页数时则用总字符数阈值判断。
_MIN_CHARS_PER_PAGE = 50


def _pymupdf_output_too_sparse(text: str, file_path: Path) -> bool:
    '''判断转换结果是否短得异常，区分解析失败与内容本来就很短的文档。'''
    chars = len(text.strip())
    doc = None
    pages: int | None = None
    try:
        import pymupdf

        doc = pymupdf.open(str(file_path))
        pages = len(doc)
    except Exception:
        pass
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
    if pages is not None and pages > 0:
        return (chars / pages) < _MIN_CHARS_PER_PAGE
    # 无法读取页数时，以绝对文本量阈值作为保守回退判断。
    return chars < 200


def _convert_pdf_with_pymupdf4llm(file_path: Path) -> str | None:
    '''尝试用 pymupdf4llm 转换 PDF；依赖缺失或解析失败时返回空值交由回退处理。'''
    try:
        import pymupdf4llm
    except ImportError:
        return None

    try:
        return pymupdf4llm.to_markdown(str(file_path))
    except Exception:
        logger.exception("pymupdf4llm failed to convert %s; falling back to MarkItDown", file_path.name)
        return None


def _convert_with_markitdown(file_path: Path) -> str:
    '''使用 MarkItDown 转换器读取文档并返回 Markdown 文本。'''
    from markitdown import MarkItDown

    md = MarkItDown()
    return md.convert(str(file_path)).text_content


def _do_convert(file_path: Path, pdf_converter: str) -> str:
    '''按配置尝试 PDF 专用转换器，并在自动模式解析质量差时回退通用转换器。'''
    is_pdf = file_path.suffix.lower() == ".pdf"

    if is_pdf and pdf_converter != "markitdown":
        # 自动模式和显式指定时都先尝试 PDF 专用转换器。
        pymupdf_text = _convert_pdf_with_pymupdf4llm(file_path)

        if pymupdf_text is not None:
            # 专用转换器已安装且成功返回内容。
            if pdf_converter == "pymupdf4llm":
                # 显式指定该转换器时尊重用户选择，不按文本长度回退。
                return pymupdf_text
            # 自动模式根据每页文本量判断是否解析失败，避免把正常短文误判为扫描件。
            if not _pymupdf_output_too_sparse(pymupdf_text, file_path):
                return pymupdf_text
            logger.warning(
                "pymupdf4llm produced only %d chars for %s (likely image-based PDF); falling back to MarkItDown",
                len(pymupdf_text.strip()),
                file_path.name,
            )
        # 专用依赖缺失或自动质量检查未通过时改由通用转换器处理。

    return _convert_with_markitdown(file_path)


async def convert_file_to_markdown(file_path: Path) -> Path | None:
    '''转换单个上传文件并写入同目录 Markdown 文件；失败时记录日志并返回空值。'''
    try:
        pdf_converter = _get_pdf_converter()
        file_size = file_path.stat().st_size

        if file_size > _ASYNC_THRESHOLD_BYTES:
            text = await asyncio.to_thread(_do_convert, file_path, pdf_converter)
        else:
            text = _do_convert(file_path, pdf_converter)

        md_path = file_path.with_suffix(".md")
        md_path.write_text(text, encoding="utf-8")

        logger.info("Converted %s to markdown: %s (%d chars)", file_path.name, md_path.name, len(text))
        return md_path
    except Exception as e:
        logger.error("Failed to convert %s to markdown: %s", file_path.name, e)
        return None


# 识别转换器未标成 Markdown 标题、但以粗体输出的证券文件结构标题。
# 要求整行只有一个粗体块且以章节关键词开头，避免将地址和固定页眉误认为标题。
_BOLD_HEADING_RE = re.compile(r"^\*\*((ITEM|PART|SECTION|SCHEDULE|EXHIBIT|APPENDIX|ANNEX|CHAPTER)\b[A-Z0-9 .,\-]*)\*\*\s*$")

# 识别编号和标题被 PDF 拆成多个粗体片段的章节行，同时排除纯数字表格表头；
# 限制片段数量和内容形态，避免对上传文本执行高复杂度正则匹配。
_SPLIT_BOLD_HEADING_RE = re.compile(r"^\*\*[\dA-Z][\d\.]*\*\*\s+\*\*(?!\d[\d\s.,\-–—/:()%]*\*\*)[^*]+\*\*(?:\s+\*\*[^*]+\*\*){0,2}\s*$")

# 限制注入智能体上下文的大纲条目数，避免长文档挤占提示空间。
MAX_OUTLINE_ENTRIES = 50

_ALLOWED_PDF_CONVERTERS = {"auto", "pymupdf4llm", "markitdown"}


def _clean_bold_title(raw: str) -> str:
    '''合并相邻粗体片段并移除整段包裹标记，得到可展示的标题文本。'''
    # 相邻粗体区块通常来自 PDF 中被拆开的连续文本。
    merged = re.sub(r"\*\*\s*\*\*", " ", raw).strip()
    # 如果整行仍由粗体标记包围，则仅去掉最外层标记。
    if m := re.fullmatch(r"\*\*(.+?)\*\*", merged, re.DOTALL):
        return m.group(1).strip()
    return merged


def extract_outline(md_path: Path) -> list[dict]:
    '''扫描转换后的 Markdown 标题，并兼容 PDF 结构标题的粗体写法。'''
    outline: list[dict] = []
    try:
        with md_path.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped:
                    continue

                # 第一种格式：标准 Markdown 标题。
                if stripped.startswith("#"):
                    title = _clean_bold_title(stripped.lstrip("#").strip())
                    if title:
                        outline.append({"title": title, "line": lineno})

                # 第二种格式：以结构关键词开头的单个粗体标题块。
                elif m := _BOLD_HEADING_RE.match(stripped):
                    title = m.group(1).strip()
                    if title:
                        outline.append({"title": title, "line": lineno})

                # 第三种格式：章节编号和标题被拆分成多个粗体块。
                elif _SPLIT_BOLD_HEADING_RE.match(stripped):
                    title = " ".join(re.findall(r"\*\*([^*]+)\*\*", stripped))
                    if title:
                        outline.append({"title": title, "line": lineno})

                if len(outline) > MAX_OUTLINE_ENTRIES:
                    # 多读到的这一项证明大纲超限；丢弃它并添加截断标记。
                    outline.pop()
                    outline.append({"truncated": True})
                    break
    except Exception:
        return []

    return outline


def _get_uploads_config_value(key: str, default: object) -> object:
    '''从应用配置读取上传转换选项，并兼容配置模型和字典两种表示。'''
    cfg = get_app_config()
    uploads_cfg = getattr(cfg, "uploads", None)
    if isinstance(uploads_cfg, dict):
        return uploads_cfg.get(key, default)
    return getattr(uploads_cfg, key, default)


def _get_pdf_converter() -> str:
    '''校验 PDF 转换器选项；配置缺失或非法时安全回退到自动模式。'''
    try:
        raw = str(_get_uploads_config_value("pdf_converter", "auto")).strip().lower()
        if raw not in _ALLOWED_PDF_CONVERTERS:
            logger.warning("Invalid pdf_converter value %r; falling back to 'auto'", raw)
            return "auto"
        return raw
    except Exception:
        pass
    return "auto"
