const MERMAID_OPENING_FENCE_RE =
  /^[ \t]{0,3}(`{3,}|~{3,})[ \t]*mermaid(?:[ \t].*)?$/i;

const WINDOWS_LINE_ENDING_RE = /\r\n?/g;

const LABELLED_DOTTED_ARROW_RE =
  /^(\s*)(.+?)\s*--\s*("[^"\n]+"|'[^'\n]+')\s*-\.->\s*(.+?)\s*$/;

/** 规范化流程图代码块内容，修复流式输出常见的空白问题。 */
function normalizeMermaidCode(code: string): string {
  return code
    .split("\n")
    .map((line) =>
      line.replace(
        LABELLED_DOTTED_ARROW_RE,
        (
          _match,
          indent: string,
          source: string,
          label: string,
          target: string,
        ) => `${indent}${source} -. ${label} .-> ${target}`,
      ),
    )
    .join("\n");
}

/** 判断一行是否关闭了指定形式的代码围栏。 */
function isClosingFence(line: string, fence: string): boolean {
  const trimmedLine = line.trimEnd();
  const indentationLength = trimmedLine.length - trimmedLine.trimStart().length;
  const fenceMarker = trimmedLine.slice(indentationLength);
  const fenceChar = fence.charAt(0);

  if (indentationLength > 3 || !fenceMarker.startsWith(fenceChar)) {
    return false;
  }

  return (
    fenceMarker.length >= fence.length &&
    [...fenceMarker].every((char) => char === fenceChar)
  );
}

/** 仅规范化标记文本中流程图围栏的代码内容。 */
export function normalizeMermaidMarkdown(markdown: string): string {
  const lines = markdown.replace(WINDOWS_LINE_ENDING_RE, "\n").split("\n");
  const normalizedLines: string[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]!;

    const openingFenceMatch = MERMAID_OPENING_FENCE_RE.exec(line);

    if (!openingFenceMatch) {
      normalizedLines.push(line);
      continue;
    }

    const openingFence = openingFenceMatch[1];

    if (openingFence === undefined) {
      normalizedLines.push(line);
      continue;
    }

    const codeLines: string[] = [];
    let closingLine: string | undefined;
    let cursor = index + 1;

    for (; cursor < lines.length; cursor += 1) {
      const candidateLine = lines[cursor]!;

      if (isClosingFence(candidateLine, openingFence)) {
        closingLine = candidateLine;
        break;
      }

      codeLines.push(candidateLine);
    }

    if (closingLine === undefined) {
      normalizedLines.push(line, ...codeLines);
      index = cursor - 1;
      continue;
    }

    normalizedLines.push(line);

    if (codeLines.length > 0) {
      normalizedLines.push(
        ...normalizeMermaidCode(codeLines.join("\n")).split("\n"),
      );
    }

    normalizedLines.push(closingLine);
    index = cursor;
  }

  return normalizedLines.join("\n");
}
