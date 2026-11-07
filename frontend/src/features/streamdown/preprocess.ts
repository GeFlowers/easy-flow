import { normalizeMermaidMarkdown } from "./mermaid";

const MERMAID_BLOCK_HINT_RE = /mermaid/i;

// 标记文本解析器的引用块分词会随嵌套层级递归；约两千层即可耗尽调用栈并使聊天页报错。
// 限制为 100 层远超正常内容所需，同时为崩溃阈值留出充足余量。
const MAX_BLOCKQUOTE_DEPTH = 100;
const DEEP_BLOCKQUOTE_HINT_RE = new RegExp(
  `^(?:[ \\t]*>){${MAX_BLOCKQUOTE_DEPTH + 1}}`,
  "m",
);
// 仅前三个前导空格可开启引用块；四个及以上空格或制表符表示缩进代码块，其中 > 是字面内容。
const BLOCKQUOTE_PREFIX_RE = /^ {0,3}(?:[ \t]*>)+/;
const CODE_FENCE_RE = /^ {0,3}(?:```|~~~)/;
const INDENTED_CODE_RE = /^(?: {4}|\t)/;

// 标记文本解析器的列表分词同样逐层递归。浏览器中深层列表会在渲染时栈溢出，较大栈则会导致二次复杂度耗尽堆内存。
// 每层至少需要约两列缩进，将前导空白限制为 200 列即可把有效深度约束在 100 层；超过该范围属于异常嵌套。
const MAX_LIST_INDENT = 200;
const DEEP_INDENT_HINT_RE = new RegExp(`^[ \\t]{${MAX_LIST_INDENT + 1},}`, "m");

/** 限制引用块嵌套深度，避免流式渲染产生过深结构。 */
export function capBlockquoteNesting(markdown: string): string {
  if (!DEEP_BLOCKQUOTE_HINT_RE.test(markdown)) {
    return markdown;
  }

  let insideFence = false;
  return markdown
    .split("\n")
    .map((line) => {
      if (CODE_FENCE_RE.test(line)) {
        insideFence = !insideFence;
        return line;
      }
      // 围栏或缩进代码块内的 > 是字面文本而非嵌套；改写会悄然损坏代码内容。
      if (insideFence || INDENTED_CODE_RE.test(line)) {
        return line;
      }
      const match = BLOCKQUOTE_PREFIX_RE.exec(line);
      if (!match) {
        return line;
      }
      const prefix = match[0];
      let depth = 0;
      for (let i = 0; i < prefix.length; i++) {
        if (prefix[i] === ">") {
          depth += 1;
          if (depth > MAX_BLOCKQUOTE_DEPTH) {
            return line.slice(0, i) + line.slice(prefix.length);
          }
        }
      }
      return line;
    })
    .join("\n");
}

/** 限制列表嵌套深度，保持流式标记文本的可渲染性。 */
export function capListNesting(markdown: string): string {
  if (!DEEP_INDENT_HINT_RE.test(markdown)) {
    return markdown;
  }

  let insideFence = false;
  return markdown
    .split("\n")
    .map((line) => {
      if (CODE_FENCE_RE.test(line)) {
        insideFence = !insideFence;
        return line;
      }
      // 围栏代码内的缩进是字面布局（如字符图或粘贴源码），折叠会损坏渲染结果。
      if (insideFence) {
        return line;
      }
      const whitespace = /^[ \t]*/.exec(line)![0];
      if (whitespace.length <= MAX_LIST_INDENT) {
        return line;
      }
      return " ".repeat(MAX_LIST_INDENT) + line.slice(whitespace.length);
    })
    .join("\n");
}

// 在交给标记文本解析器前限制所有可能拖垮消息渲染的失控嵌套结构。
/** 同时约束引用块与列表的嵌套层级。 */
export function capMarkdownNesting(markdown: string): string {
  return capListNesting(capBlockquoteNesting(markdown));
}

type MathDelimiter = {
  close: "\\)" | "\\]";
  replacement: "$" | "$$";
};

type DelimiterState = {
  openBlock: MathDelimiter | null;
  inlineCodeDelimiterLength: number | null;
};

/** 读取当前位置连续反引号的结束索引。 */
function consumeBacktickRun(line: string, index: number): number {
  let runLength = 0;
  while (line[index + runLength] === "`") {
    runLength += 1;
  }
  return runLength;
}

/** 在非代码片段中将兼容的公式分隔符转换为统一格式。 */
function convertLatexDelimitersInLine(
  line: string,
  state: DelimiterState,
): { line: string; state: DelimiterState } {
  let result = "";
  let i = 0;
  let inlineCodeDelimiterLength = state.inlineCodeDelimiterLength;
  let currentBlock = state.openBlock;

  while (i < line.length) {
    if (line[i] === "`") {
      const runLength = consumeBacktickRun(line, i);
      result += line.slice(i, i + runLength);
      if (!currentBlock) {
        if (inlineCodeDelimiterLength === null) {
          inlineCodeDelimiterLength = runLength;
        } else if (runLength === inlineCodeDelimiterLength) {
          inlineCodeDelimiterLength = null;
        }
      }
      i += runLength;
      continue;
    }

    const two = line.slice(i, i + 2);
    const inInlineCode = inlineCodeDelimiterLength !== null;

    // 将转义反斜杠作为整体消费；\\ 不属于数学分隔符，跳过两字符可避免第二个反斜杠与后续括号误配。
    if (two === "\\\\" && !inInlineCode) {
      result += two;
      i += 2;
      continue;
    }

    // 关闭已开启的数学块。
    if (!inInlineCode && currentBlock?.close === two) {
      result += currentBlock.replacement;
      currentBlock = null;
      i += 2;
      continue;
    }

    // 开启新的数学块。
    if (!inInlineCode && !currentBlock && (two === "\\(" || two === "\\[")) {
      const isDisplay = two === "\\[";
      currentBlock = {
        close: isDisplay ? "\\]" : "\\)",
        replacement: isDisplay ? "$$" : "$",
      };
      result += currentBlock.replacement;
      i += 2;
      continue;
    }

    result += line[i];
    i += 1;
  }

  return {
    line: result,
    state: { openBlock: currentBlock, inlineCodeDelimiterLength },
  };
}

/**
 * 为数学扩展规范化模型常见的公式分隔符。
 *
 * 数学扩展识别 `$...$` 与 `$$...$$`，但许多模型输出
 * `\(...\)` 与 `\[...\]`。在围栏／缩进代码之外转换这些分隔符，
 * 使公式渲染器能渲染公式而不破坏代码块。转换需跨行保留状态，
 * 因为显示数学通常跨越
 * 多行：
 *
 *   \[
 *   ...
 *   \]
 */
/** 规范化流式标记文本中的行内与块级公式分隔符。 */
export function normalizeLatexMathDelimiters(markdown: string): string {
  if (!/[\\][([\])]/.test(markdown)) {
    return markdown;
  }

  let insideFence = false;
  let mathState: DelimiterState = {
    openBlock: null,
    inlineCodeDelimiterLength: null,
  };

  return markdown
    .split("\n")
    .map((line) => {
      if (CODE_FENCE_RE.test(line) && !mathState.openBlock) {
        insideFence = !insideFence;
        return line;
      }
      if (
        insideFence ||
        (INDENTED_CODE_RE.test(line) && !mathState.openBlock)
      ) {
        return line;
      }
      const converted = convertLatexDelimitersInLine(line, mathState);
      mathState = converted.state;
      return converted.line;
    })
    .join("\n");
}

/** 判断公式行中是否存在未转义的注释起始符。 */
function hasUnescapedTexComment(line: string): boolean {
  for (let i = 0; i < line.length; i++) {
    if (line[i] !== "%") {
      continue;
    }

    let backslashCount = 0;
    for (let j = i - 1; j >= 0 && line[j] === "\\"; j--) {
      backslashCount += 1;
    }

    if (backslashCount % 2 === 0) {
      return true;
    }
  }

  return false;
}

/** 压平显示数学块中的空行，同时保留公式注释边界。 */
function flattenDisplayMathBody(lines: string[]): string[] {
  if (lines.some(hasUnescapedTexComment)) {
    return lines;
  }

  return [lines.map((line) => line.trim()).join(" ")];
}

/**
 * 保持完整显示数学块在流式渲染组件中不可分割。
 *
 * 流式渲染组件会先借助标记文本解析器将标记文本切分为渲染块，再对每个块运行
 * 标记渲染器。多行 `$$ ... $$` 可能在
 * 数学扩展看到成对分隔符前被切开，长编号
 * 回复中尤其明显。压缩起止 `$$` 间内容
 * 可保留公式语义（视觉换行仍由 `\\`、
 * 对齐、矩阵、分段等公式控制符），同时让显示数学块
 * 对流式渲染组件的分割器保持原子性。
 */
/** 压紧显示数学块，避免流式分段破坏数学渲染。 */
export function compactDisplayMathBlocks(markdown: string): string {
  if (!markdown.includes("$$")) {
    return markdown;
  }

  const output: string[] = [];
  let insideFence = false;
  let mathLines: string[] | null = null;

  for (const line of markdown.split("\n")) {
    if (CODE_FENCE_RE.test(line) && mathLines === null) {
      insideFence = !insideFence;
      output.push(line);
      continue;
    }

    if (insideFence || (INDENTED_CODE_RE.test(line) && mathLines === null)) {
      output.push(line);
      continue;
    }

    if (line.trim() === "$$") {
      if (mathLines === null) {
        mathLines = [];
      } else {
        const flattenedMathLines = flattenDisplayMathBody(mathLines);
        output.push("$$", ...flattenedMathLines, "$$");
        mathLines = null;
      }
      continue;
    }

    if (mathLines !== null) {
      mathLines.push(line);
      continue;
    }

    output.push(line);
  }

  if (mathLines !== null) {
    output.push("$$", ...mathLines);
  }

  return output.join("\n");
}

/** 为流式渲染组件依次应用数学相关的标记文本规范化。 */
export function normalizeStreamdownMathMarkdown(markdown: string): string {
  return compactDisplayMathBlocks(normalizeLatexMathDelimiters(markdown));
}

/** 在出现异常箭头时规范化流式渲染中的流程图代码块。 */
export function preprocessStreamdownMarkdown(markdown: string): string {
  if (!MERMAID_BLOCK_HINT_RE.test(markdown) || !markdown.includes("-.->")) {
    return markdown;
  }

  return normalizeMermaidMarkdown(markdown);
}
