'''将网页 HTML 正文提取为文章对象，并转换为 Markdown 或多模态消息。'''

import logging
import re
import subprocess
from urllib.parse import urljoin

from markdownify import markdownify as md
from readabilipy import simple_json_from_html_string

logger = logging.getLogger(__name__)


class Article:
    '''保存网页标题和正文 HTML，供摘要工具选择不同输出格式。'''

    url: str

    def __init__(self, title: str, html_content: str):
        '''将正文 HTML 转成 Markdown，可按需在开头加入文章标题。'''
        self.title = title
        self.html_content = html_content

    def to_markdown(self, including_title: bool = True) -> str:
        '''把 Markdown 中的图片链接拆成文本块和图片块供多模态模型读取。'''
        markdown = ""
        if including_title:
            markdown += f"# {self.title}\n\n"

        if self.html_content is None or not str(self.html_content).strip():
            markdown += "*No content available*\n"
        else:
            markdown += md(self.html_content)

        return markdown

    def to_message(self) -> list[dict]:
        '''将 Markdown 正文拆分为文本和图片块，并把相对图片地址解析为绝对地址。'''
        image_pattern = r"!\[.*?\]\((.*?)\)"

        content: list[dict[str, str]] = []
        markdown = self.to_markdown()

        if not markdown or not markdown.strip():
            return [{"type": "text", "text": "No content available"}]

        parts = re.split(image_pattern, markdown)

        for i, part in enumerate(parts):
            if i % 2 == 1:
                image_url = urljoin(self.url, part.strip())
                content.append({"type": "image_url", "image_url": {"url": image_url}})
            else:
                text_part = part.strip()
                if text_part:
                    content.append({"type": "text", "text": text_part})

                # 普通 Markdown 片段以文本块保留，图片 URL 则在上方单独转换。
        if not content:
            content = [{"type": "text", "text": "No content available"}]

        return content


class ReadabilityExtractor:
    '''优先使用 Readability 提取正文，外部解析器失败时回退到纯 Python 提取。'''

    def extract_article(self, html: str) -> Article:
        '''调用 Readability 提取网页正文；命令或依赖故障时使用纯 Python 模式重试。'''
        try:
            article = simple_json_from_html_string(html, use_readability=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            stderr = getattr(exc, "stderr", None)
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            stderr_info = f"; stderr={stderr.strip()}" if isinstance(stderr, str) and stderr.strip() else ""
            logger.warning(
                "Readability.js extraction failed with %s%s; falling back to pure-Python extraction",
                type(exc).__name__,
                stderr_info,
                exc_info=True,
            )
            article = simple_json_from_html_string(html, use_readability=False)

        html_content = article.get("content")
        if not html_content or not str(html_content).strip():
            html_content = "No content could be extracted from this page"

        title = article.get("title")
        if not title or not str(title).strip():
            title = "Untitled"

        return Article(title=title, html_content=html_content)
