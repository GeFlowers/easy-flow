/** 记录同一引用来源在 Markdown 中的一次出现位置。 */
export type CitationOccurrence = {
  index: number;
  title: string;
};

/** 聚合同一 URL 的引用来源及其显示与位置信息。 */
export type CitationSource = {
  id: string;
  title: string;
  url: string;
  domain: string;
  count: number;
  occurrences: CitationOccurrence[];
};

// 使用非消耗式后行断言 (?<!!) 跳过图片链接（![citation:…]）且不吞掉边界字符，
// 因而连续引用都可匹配。URL 子模式可消费非括号字符或成对的 (…) 片段，避免
// .../Foo_(a)_(b) 这类消歧 URL 在第一个内层括号处被截断。
const CITATION_LINK_RE =
  /(?<!!)\[citation:\s*([^\]]+?)\]\((https?:\/\/(?:[^\s()]|\([^\s()]*\))+)\)/gi;

const GENERIC_CITATION_TITLES = new Set(["source", "来源"]);

/** 从 Markdown 中提取可见引用，按规范化 URL 合并并记录出现位置。 */
export function extractCitationSources(markdown: string): CitationSource[] {
  if (!markdown) {
    return [];
  }

  const searchable = maskCode(markdown);
  const sourcesByUrl = new Map<string, CitationSource>();

  for (const match of searchable.matchAll(CITATION_LINK_RE)) {
    const rawTitle = (match[1] ?? "").trim();
    const rawUrl = match[2] ?? "";
    const url = normalizeUrl(rawUrl);
    if (!url) {
      continue;
    }

    const domain = extractDomain(url);
    const title = normalizeTitle(rawTitle, domain);
    const index = match.index ?? 0;
    const existing = sourcesByUrl.get(url);

    if (existing) {
      existing.count += 1;
      existing.occurrences.push({ index, title });
      continue;
    }

    sourcesByUrl.set(url, {
      id: url,
      title,
      url,
      domain,
      count: 1,
      occurrences: [{ index, title }],
    });
  }

  return Array.from(sourcesByUrl.values());
}

/** 将引用来源格式化为可插回 Markdown 的链接。 */
export function formatCitationMarkdownReference(
  source: CitationSource,
): string {
  return `[${source.title}](${source.url})`;
}

/** 整理引用标题；缺失或通用标题时回退为域名。 */
function normalizeTitle(title: string, domain: string): string {
  const compact = title.replace(/\s+/g, " ").trim();
  if (!compact || GENERIC_CITATION_TITLES.has(compact.toLowerCase())) {
    return domain;
  }
  return compact;
}

/** 验证并规范化 HTTP(S) 引用地址。 */
function normalizeUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
    return url.href;
  } catch {
    return null;
  }
}

/** 从 URL 提取不含 `www.` 前缀的域名。 */
function extractDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./i, "");
  } catch {
    return url;
  }
}

// 将代码区域置空，避免代码示例中的引用被识别为真实来源；同时保留字符串长度和换行，
// 使出现位置索引仍与原始 Markdown 对齐。
/** 屏蔽 Markdown 中的代码区域，防止其中的示例链接被识别为引用。 */
function maskCode(markdown: string): string {
  return maskInlineCode(maskFencedCodeBlocks(markdown));
}

/** 屏蔽围栏代码块；未闭合的流式代码块会屏蔽至文本结尾。 */
function maskFencedCodeBlocks(markdown: string): string {
  // 匹配围栏代码块至对应结束围栏；消息仍在流式传输且围栏未闭合时则匹配至输入末尾。
  return markdown.replace(
    /(^|\n)(`{3,}|~{3,})[^\n]*(?:\n[\s\S]*?\n\2[^\n]*(?=\n|$)|[\s\S]*$)/g,
    maskKeepingNewlines,
  );
}

/** 屏蔽已闭合的行内代码，保留未闭合反引号后的可见文本。 */
function maskInlineCode(markdown: string): string {
  // 仅屏蔽闭合区段：未闭合的反引号会按普通文本渲染，其后的引用是真实可见链接，不能屏蔽。
  return markdown.replace(/(`+)[\s\S]*?\1/g, maskKeepingNewlines);
}

/** 以空格替换非换行字符，保持原始索引和行结构不变。 */
function maskKeepingNewlines(block: string): string {
  return block.replace(/[^\n]/g, " ");
}
