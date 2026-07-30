/** 从标记文本内容中提取首个一级标题。 */
export function extractTitleFromMarkdown(markdown: string) {
  if (markdown.startsWith("# ")) {
    let title = markdown.split("\n")[0]!.trim();
    if (title.startsWith("# ")) {
      title = title.slice(2).trim();
    }
    return title;
  }
  return undefined;
}
