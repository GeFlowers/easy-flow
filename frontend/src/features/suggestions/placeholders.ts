/**
 * 匹配已知建议模板占位符的正则表达式。
 *
 * 这些是语言文件中建议提示词模板使用的精确占位符标记。
 *
 * 模板新增占位符标记时，必须同步更新该模式。
 */
export const SUGGESTION_TEMPLATE_PLACEHOLDER_PATTERN =
  /\[(?:主题|来源|topic|source)\]/i;

/**
 * 在给定文本中定位尚未替换的建议模板占位符。
 *
 * 找到时返回占位符的起止字符索引；文本未包含已知占位符标记时返回空值。
 */
/** 查找建议模板中位于指定光标位置的占位符。 */
export function findSuggestionTemplatePlaceholder(
  text: string,
): { start: number; end: number } | null {
  const match = SUGGESTION_TEMPLATE_PLACEHOLDER_PATTERN.exec(text);
  if (!match) {
    return null;
  }

  return {
    start: match.index,
    end: match.index + match[0].length,
  };
}
