/** 兼容原生与回退实现的最小剪贴板条目结构。 */
type ClipboardItemLike = {
  types?: readonly string[];
  getType?: (type: string) => Promise<Blob>;
  items?: Record<string, Blob | string>;
};

/** 在 Clipboard API 不可用时，通过临时文本域与 `execCommand` 复制纯文本。 */
function copyTextWithExecCommand(text: string): boolean {
  const document = globalThis.document;
  if (
    typeof document?.createElement !== "function" ||
    typeof document.body?.appendChild !== "function" ||
    typeof document.execCommand !== "function"
  ) {
    throw new Error("Clipboard DOM fallback not available");
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "-9999px";
  textarea.style.left = "-9999px";

  let copied = false;
  let appended = false;
  try {
    document.body.appendChild(textarea);
    appended = true;
    textarea.select();
    copied = document.execCommand("copy");
  } finally {
    if (appended) {
      const parentNode = textarea.parentNode;
      if (typeof textarea.remove === "function") {
        textarea.remove();
      } else if (typeof parentNode?.removeChild === "function") {
        parentNode.removeChild(textarea);
      }
    }
  }

  return copied;
}

/** 优先使用浏览器 Clipboard API 写入文本，并在受限环境中回退到兼容方案。 */
export async function writeTextToClipboard(text: string): Promise<boolean> {
  try {
    const clipboard = globalThis.navigator?.clipboard;
    if (clipboard?.writeText) {
      await clipboard.writeText(text);
      return true;
    }

    return copyTextWithExecCommand(text);
  } catch {
    return false;
  }
}

/** 调用 `execCommand` 兼容方案；复制失败时返回拒绝的 Promise 以保持 API 语义一致。 */
function fallbackWriteText(text: string): Promise<void> {
  try {
    if (!copyTextWithExecCommand(text)) {
      return Promise.reject(new Error("Clipboard copy command failed"));
    }
  } catch (error) {
    return Promise.reject(
      error instanceof Error ? error : new Error(String(error)),
    );
  }
  return Promise.resolve();
}

/** 判断运行环境是否已提供可构造的 `ClipboardItem`。 */
function hasUsableClipboardItem(): boolean {
  return typeof globalThis.ClipboardItem === "function";
}

/** 从单个 ClipboardItem 中读取可用的 `text/plain` 内容。 */
async function readPlainTextFromClipboardItem(
  item: ClipboardItemLike,
): Promise<string> {
  const plainText = item.items?.["text/plain"];
  if (typeof plainText === "string") {
    return plainText;
  }
  if (plainText instanceof Blob) {
    return await plainText.text();
  }

  if (item.types && !item.types.includes("text/plain")) {
    throw new Error("Clipboard item is missing text/plain data");
  }

  if (typeof item.getType !== "function") {
    throw new Error("Clipboard item cannot read text/plain data");
  }

  const blob = await item.getType("text/plain");
  if (blob instanceof Blob) {
    return await blob.text();
  }

  throw new Error("Clipboard item text/plain data is not a Blob");
}

/** 判断当前 `navigator` 是否允许定义或替换 `clipboard` 属性。 */
function canDefineNavigatorClipboard(
  navigator: Navigator,
  descriptor: PropertyDescriptor | undefined,
): boolean {
  if (descriptor) {
    return descriptor.configurable === true;
  }
  return Object.isExtensible(navigator);
}

/**
 * 为 Streamdown 复制控件补齐浏览器剪贴板兼容能力；仅在宿主允许时填补缺失的
 * `navigator.clipboard` 方法和 `ClipboardItem`。
 */
export function installClipboardFallback(): void {
  const navigator = globalThis.navigator;
  if (!navigator) {
    return;
  }

  const rawClipboard = navigator.clipboard;
  const clipboard =
    typeof rawClipboard === "object" && rawClipboard !== null
      ? (rawClipboard as Partial<Clipboard>)
      : undefined;
  const clipboardDescriptor = Object.getOwnPropertyDescriptor(
    navigator,
    "clipboard",
  );
  const hasWriteText = typeof clipboard?.writeText === "function";
  const hasWrite = typeof clipboard?.write === "function";
  const hasClipboardItem = hasUsableClipboardItem();

  if (hasWriteText && hasWrite && hasClipboardItem) {
    return;
  }

  const writeText = hasWriteText
    ? clipboard.writeText!.bind(clipboard)
    : fallbackWriteText;
  const write = hasWrite
    ? clipboard.write!.bind(clipboard)
    : (items: ClipboardItemLike[]) => {
        const firstItem = items[0];
        if (!firstItem) {
          return Promise.reject(new Error("Clipboard item not available"));
        }

        return readPlainTextFromClipboardItem(firstItem).then(writeText);
      };

  const fallbackClipboard = clipboard ?? {};

  try {
    const missingMethods: PropertyDescriptorMap = {};
    if (!hasWrite) {
      missingMethods.write = {
        configurable: true,
        value: write,
        writable: true,
      };
    }
    if (!hasWriteText) {
      missingMethods.writeText = {
        configurable: true,
        value: writeText,
        writable: true,
      };
    }

    Object.defineProperties(fallbackClipboard, missingMethods);

    if (
      !clipboard &&
      canDefineNavigatorClipboard(navigator, clipboardDescriptor)
    ) {
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: fallbackClipboard,
      });
    }
  } catch {
    if (!canDefineNavigatorClipboard(navigator, clipboardDescriptor)) {
      // 下方的 ClipboardItem 兼容分支不依赖 navigator.clipboard。
      if (hasClipboardItem) {
        return;
      }
    } else {
      const replacement = Object.create(clipboard ?? null);
      for (const methodName of ["read", "readText"] as const) {
        const method = clipboard?.[methodName];
        if (typeof method === "function") {
          Object.defineProperty(replacement, methodName, {
            configurable: true,
            value: method.bind(clipboard),
            writable: true,
          });
        }
      }
      Object.defineProperties(replacement, {
        write: {
          configurable: true,
          value: write,
          writable: true,
        },
        writeText: {
          configurable: true,
          value: writeText,
          writable: true,
        },
      });
      try {
        Object.defineProperty(navigator, "clipboard", {
          configurable: true,
          value: replacement,
        });
      } catch {
        // 下方的 ClipboardItem 兼容分支不依赖 navigator.clipboard。
      }
    }
  }

  if (!hasClipboardItem) {
    /** 为缺少原生构造器的浏览器提供最小 `ClipboardItem` 兼容实现。 */
    class ClipboardItemFallback {
      items: Record<string, Blob | string>;
      types: string[];

      constructor(items: Record<string, Blob | string>) {
        this.items = items;
        this.types = Object.keys(items);
      }

      getType(type: string): Promise<Blob> {
        const value = this.items[type];
        if (value instanceof Blob) {
          return Promise.resolve(value);
        }
        if (typeof value === "string") {
          return Promise.resolve(new Blob([value], { type }));
        }
        return Promise.reject(
          new Error(`Clipboard item is missing ${type} data`),
        );
      }
    }

    try {
      Object.defineProperty(globalThis, "ClipboardItem", {
        configurable: true,
        value: ClipboardItemFallback,
      });
    } catch {
      return;
    }
  }
}
