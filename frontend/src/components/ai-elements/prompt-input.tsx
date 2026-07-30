"use client";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@/components/ui/input-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { PromptInputFilePart } from "@/core/uploads";
import { splitUnsupportedUploadFiles } from "@/core/uploads";
import { isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";
import type { ChatStatus } from "ai";
import {
  ArrowUpIcon,
  ImageIcon,
  Loader2Icon,
  MicIcon,
  PaperclipIcon,
  PlusIcon,
  SquareIcon,
  UploadIcon,
  XIcon,
} from "lucide-react";
import { nanoid } from "nanoid";
import {
  type ChangeEvent,
  type ChangeEventHandler,
  Children,
  type ClipboardEventHandler,
  type ComponentProps,
  createContext,
  type FormEvent,
  type FormEventHandler,
  Fragment,
  type HTMLAttributes,
  type KeyboardEventHandler,
  type PropsWithChildren,
  type ReactNode,
  type RefObject,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

// ============================================================================
// Provider 上下文与类型。
// ============================================================================

/** AttachmentsContext 的公开类型定义。 */
export type AttachmentsContext = {
  files: (PromptInputFilePart & { id: string })[];
  add: (files: File[] | FileList) => void;
  remove: (id: string) => void;
  clear: () => void;
  openFileDialog: () => void;
  fileInputRef: RefObject<HTMLInputElement | null>;
};

/** TextInputContext 的公开类型定义。 */
export type TextInputContext = {
  value: string;
  setInput: (v: string) => void;
  clear: () => void;
};

/** PromptInputControllerProps 的公开类型定义。 */
export type PromptInputControllerProps = {
  textInput: TextInputContext;
  attachments: AttachmentsContext;
  /** 内部使用：允许 PromptInput 注册文件输入框及其“打开”回调。 */
  __registerFileInput: (
    ref: RefObject<HTMLInputElement | null>,
    open: () => void,
  ) => void;
};

const PromptInputController = createContext<PromptInputControllerProps | null>(
  null,
);
const ProviderAttachmentsContext = createContext<AttachmentsContext | null>(
  null,
);
const PromptInputValidationContext = createContext<
  ((files: File[] | FileList) => File[]) | null
>(null);

/** usePromptInputController Hook：封装相关状态与交互逻辑。 */
export const usePromptInputController = () => {
  const ctx = useContext(PromptInputController);
  if (!ctx) {
    throw new Error(
      "Wrap your component inside <PromptInputProvider> to use usePromptInputController().",
    );
  }
  return ctx;
};

// 可选变体（不得抛错），供双模式组件使用。
/** useOptionalPromptInputController Hook：封装本模块所需的状态或上下文访问。 */
const useOptionalPromptInputController = () =>
  useContext(PromptInputController);

/** useProviderAttachments Hook：封装相关状态与交互逻辑。 */
export const useProviderAttachments = () => {
  const ctx = useContext(ProviderAttachmentsContext);
  if (!ctx) {
    throw new Error(
      "Wrap your component inside <PromptInputProvider> to use useProviderAttachments().",
    );
  }
  return ctx;
};

/** useOptionalProviderAttachments Hook：封装本模块所需的状态或上下文访问。 */
const useOptionalProviderAttachments = () =>
  useContext(ProviderAttachmentsContext);
/** usePromptInputValidation Hook：封装本模块所需的状态或上下文访问。 */
const usePromptInputValidation = () => useContext(PromptInputValidationContext);

/** PromptInputProviderProps 的公开类型定义。 */
export type PromptInputProviderProps = PropsWithChildren<{
  initialInput?: string;
}>;

/**
 * 可选的全局 Provider，用于将 PromptInput 状态提升至组件外部。
 * 未使用该 Provider 时，PromptInput 继续在组件内部独立管理状态。
 */
export function PromptInputProvider({
  initialInput: initialTextInput = "",
  children,
}: PromptInputProviderProps) {
  // ----- 文本输入状态。
  const [textInput, setTextInput] = useState(initialTextInput);
  const clearInput = useCallback(() => setTextInput(""), []);

  // ----- 附件状态（被 Provider 包裹时为全局状态）。
  const [attachmentFiles, setAttachmentFiles] = useState<
    (PromptInputFilePart & { id: string })[]
  >([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const openRef = useRef<() => void>(() => {});

  const add = useCallback((files: File[] | FileList) => {
    const incoming = Array.from(files);
    if (incoming.length === 0) {
      return;
    }

    setAttachmentFiles((prev) =>
      prev.concat(
        incoming.map((file) => ({
          id: nanoid(),
          type: "file" as const,
          url: URL.createObjectURL(file),
          mediaType: file.type,
          filename: file.name,
          file,
        })),
      ),
    );
  }, []);

  const remove = useCallback((id: string) => {
    setAttachmentFiles((prev) => {
      const found = prev.find((f) => f.id === id);
      if (found?.url) {
        URL.revokeObjectURL(found.url);
      }
      return prev.filter((f) => f.id !== id);
    });
  }, []);

  const clear = useCallback(() => {
    setAttachmentFiles((prev) => {
      for (const f of prev) {
        if (f.url) {
          URL.revokeObjectURL(f.url);
        }
      }
      return [];
    });
  }, []);

  // 保留附件引用以便卸载时清理，并避免闭包读取过期值。
  const attachmentsRef = useRef(attachmentFiles);
  attachmentsRef.current = attachmentFiles;

  // 卸载时释放 Blob URL，避免内存泄漏。
  useEffect(() => {
    return () => {
      for (const f of attachmentsRef.current) {
        if (f.url) {
          URL.revokeObjectURL(f.url);
        }
      }
    };
  }, []);

  const openFileDialog = useCallback(() => {
    openRef.current?.();
  }, []);

  const attachments = useMemo<AttachmentsContext>(
    () => ({
      files: attachmentFiles,
      add,
      remove,
      clear,
      openFileDialog,
      fileInputRef,
    }),
    [attachmentFiles, add, remove, clear, openFileDialog],
  );

  const __registerFileInput = useCallback(
    (ref: RefObject<HTMLInputElement | null>, open: () => void) => {
      fileInputRef.current = ref.current;
      openRef.current = open;
    },
    [],
  );

  const controller = useMemo<PromptInputControllerProps>(
    () => ({
      textInput: {
        value: textInput,
        setInput: setTextInput,
        clear: clearInput,
      },
      attachments,
      __registerFileInput,
    }),
    [textInput, clearInput, attachments, __registerFileInput],
  );

  return (
    <PromptInputController.Provider value={controller}>
      <ProviderAttachmentsContext.Provider value={attachments}>
        {children}
      </ProviderAttachmentsContext.Provider>
    </PromptInputController.Provider>
  );
}

// ============================================================================
// 组件上下文与 Hook。
// ============================================================================

const LocalAttachmentsContext = createContext<AttachmentsContext | null>(null);

/** usePromptInputAttachments Hook：封装相关状态与交互逻辑。 */
export const usePromptInputAttachments = () => {
  // 双模式：优先使用 Provider；不存在时使用本地状态。
  const provider = useOptionalProviderAttachments();
  const local = useContext(LocalAttachmentsContext);
  const context = provider ?? local;
  if (!context) {
    throw new Error(
      "usePromptInputAttachments must be used within a PromptInput or PromptInputProvider",
    );
  }
  return context;
};

/** PromptInputAttachmentProps 的公开类型定义。 */
export type PromptInputAttachmentProps = HTMLAttributes<HTMLDivElement> & {
  data: PromptInputFilePart & { id: string };
  className?: string;
};

/** PromptInputAttachment 组件：提供对应的界面结构与交互语义。 */
export function PromptInputAttachment({
  data,
  className,
  ...props
}: PromptInputAttachmentProps) {
  const attachments = usePromptInputAttachments();

  const filename = data.filename || "";

  const mediaType =
    data.mediaType?.startsWith("image/") && data.url ? "image" : "file";
  const isImage = mediaType === "image";

  const attachmentLabel = filename || (isImage ? "Image" : "Attachment");

  return (
    <PromptInputHoverCard>
      <HoverCardTrigger asChild>
        <div
          className={cn(
            "group border-border hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50 relative flex h-8 cursor-pointer items-center gap-1.5 rounded-md border px-1.5 text-sm font-medium transition-all select-none",
            className,
          )}
          key={data.id}
          {...props}
        >
          <div className="relative size-5 shrink-0">
            <div className="bg-background absolute inset-0 flex size-5 items-center justify-center overflow-hidden rounded transition-opacity group-hover:opacity-0">
              {isImage ? (
                <img
                  alt={filename || "attachment"}
                  className="size-5 object-cover"
                  height={20}
                  src={data.url}
                  width={20}
                />
              ) : (
                <div className="text-muted-foreground flex size-5 items-center justify-center">
                  <PaperclipIcon className="size-3" />
                </div>
              )}
            </div>
            <Button
              aria-label="Remove attachment"
              className="absolute inset-0 size-5 cursor-pointer rounded p-0 opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 [&>svg]:size-2.5"
              onClick={(e) => {
                e.stopPropagation();
                attachments.remove(data.id);
              }}
              type="button"
              variant="ghost"
            >
              <XIcon />
              <span className="sr-only">Remove</span>
            </Button>
          </div>

          <span className="flex-1 truncate">{attachmentLabel}</span>
        </div>
      </HoverCardTrigger>
      <PromptInputHoverCardContent className="w-auto p-2">
        <div className="w-auto space-y-3">
          {isImage && (
            <div className="flex max-h-96 w-96 items-center justify-center overflow-hidden rounded-md border">
              <img
                alt={filename || "attachment preview"}
                className="max-h-full max-w-full object-contain"
                height={384}
                src={data.url}
                width={448}
              />
            </div>
          )}
          <div className="flex items-center gap-2.5">
            <div className="min-w-0 flex-1 space-y-1 px-0.5">
              <h4 className="truncate text-sm leading-none font-semibold">
                {filename || (isImage ? "Image" : "Attachment")}
              </h4>
              {data.mediaType && (
                <p className="text-muted-foreground truncate font-mono text-xs">
                  {data.mediaType}
                </p>
              )}
            </div>
          </div>
        </div>
      </PromptInputHoverCardContent>
    </PromptInputHoverCard>
  );
}

/** PromptInputAttachmentsProps 的公开类型定义。 */
export type PromptInputAttachmentsProps = Omit<
  HTMLAttributes<HTMLDivElement>,
  "children"
> & {
  children: (attachment: PromptInputFilePart & { id: string }) => ReactNode;
};

/** PromptInputAttachments 组件：提供对应的界面结构与交互语义。 */
export function PromptInputAttachments({
  children,
  className,
  ...props
}: PromptInputAttachmentsProps) {
  const attachments = usePromptInputAttachments();

  if (!attachments.files.length) {
    return null;
  }

  return (
    <div
      className={cn("flex w-full flex-wrap items-center gap-2 p-3", className)}
      {...props}
    >
      {attachments.files.map((file) => (
        <Fragment key={file.id}>
          <div className="max-w-60">{children(file)}</div>
        </Fragment>
      ))}
    </div>
  );
}

/** PromptInputActionAddAttachmentsProps 的公开类型定义。 */
export type PromptInputActionAddAttachmentsProps = ComponentProps<
  typeof DropdownMenuItem
> & {
  label?: string;
};

/** PromptInputActionAddAttachments 组件：提供对应的界面结构与交互语义。 */
export const PromptInputActionAddAttachments = ({
  label = "Add photos or files",
  ...props
}: PromptInputActionAddAttachmentsProps) => {
  const attachments = usePromptInputAttachments();

  return (
    <DropdownMenuItem
      {...props}
      onSelect={(e) => {
        e.preventDefault();
        attachments.openFileDialog();
      }}
    >
      <PaperclipIcon className="mr-2 size-4" /> {label}
    </DropdownMenuItem>
  );
};

/** PromptInputMessage 的公开类型定义。 */
export type PromptInputMessage = {
  text: string;
  files: PromptInputFilePart[];
};

/** PromptInputProps 的公开类型定义。 */
export type PromptInputProps = Omit<
  HTMLAttributes<HTMLFormElement>,
  "onSubmit" | "onError"
> & {
  accept?: string; // 例如“image/*”；未定义时接受任意类型。
  disabled?: boolean;
  multiple?: boolean;
  // 为 true 时接受文档任意位置的拖放；默认 false，需显式启用。
  globalDrop?: boolean;
  // 渲染指定 name 的隐藏输入框，并为原生表单提交保持同步；默认 false。
  syncHiddenInput?: boolean;
  // 最小约束。
  maxFiles?: number;
  maxFileSize?: number; // bytes
  onError?: (err: {
    code: "max_files" | "max_file_size" | "accept" | "unsupported_package";
    message: string;
  }) => void;
  onSubmit: (
    message: PromptInputMessage,
    event: FormEvent<HTMLFormElement>,
  ) => void | Promise<void>;
};

/** PromptInput 组件：提供对应的界面结构与交互语义。 */
export const PromptInput = ({
  className,
  accept,
  disabled,
  multiple,
  globalDrop,
  syncHiddenInput,
  maxFiles,
  maxFileSize,
  onError,
  onSubmit,
  children,
  ...props
}: PromptInputProps) => {
  // 如存在则优先使用 Provider 控制器。
  const controller = useOptionalPromptInputController();
  const usingProvider = !!controller;

  // 引用。
  const inputRef = useRef<HTMLInputElement | null>(null);
  const formRef = useRef<HTMLFormElement | null>(null);

  // ----- 本地附件（仅在没有 Provider 时使用）。
  const [items, setItems] = useState<(PromptInputFilePart & { id: string })[]>(
    [],
  );
  const files = usingProvider ? controller.attachments.files : items;

  // 保留文件引用以便卸载时清理，并避免闭包读取过期值。
  const filesRef = useRef(files);
  filesRef.current = files;
  const providerTextRef = useRef("");
  if (usingProvider) {
    providerTextRef.current = controller.textInput.value;
  }

  const openFileDialogLocal = useCallback(() => {
    inputRef.current?.click();
  }, []);

  const matchesAccept = useCallback(
    (f: File) => {
      if (!accept || accept.trim() === "") {
        return true;
      }

      const patterns = accept
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);

      return patterns.some((pattern) => {
        if (pattern.endsWith("/*")) {
          const prefix = pattern.slice(0, -1); // 例如：image/* 变为 image/。
          return f.type.startsWith(prefix);
        }
        return f.type === pattern;
      });
    },
    [accept],
  );

  const addLocal = useCallback(
    (fileList: File[] | FileList) => {
      const incoming = Array.from(fileList);
      const accepted = incoming.filter((f) => matchesAccept(f));
      if (incoming.length && accepted.length === 0) {
        onError?.({
          code: "accept",
          message: "No files match the accepted types.",
        });
        return;
      }
      const withinSize = (f: File) =>
        maxFileSize ? f.size <= maxFileSize : true;
      const sized = accepted.filter(withinSize);
      if (accepted.length > 0 && sized.length === 0) {
        onError?.({
          code: "max_file_size",
          message: "All files exceed the maximum size.",
        });
        return;
      }

      setItems((prev) => {
        const capacity =
          typeof maxFiles === "number"
            ? Math.max(0, maxFiles - prev.length)
            : undefined;
        const capped =
          typeof capacity === "number" ? sized.slice(0, capacity) : sized;
        if (typeof capacity === "number" && sized.length > capacity) {
          onError?.({
            code: "max_files",
            message: "Too many files. Some were not added.",
          });
        }
        const next: (PromptInputFilePart & { id: string })[] = [];
        for (const file of capped) {
          next.push({
            id: nanoid(),
            type: "file",
            url: URL.createObjectURL(file),
            mediaType: file.type,
            filename: file.name,
            file,
          });
        }
        return prev.concat(next);
      });
    },
    [matchesAccept, maxFiles, maxFileSize, onError],
  );

  const removeLocal = useCallback(
    (id: string) =>
      setItems((prev) => {
        const found = prev.find((file) => file.id === id);
        if (found?.url) {
          URL.revokeObjectURL(found.url);
        }
        return prev.filter((file) => file.id !== id);
      }),
    [],
  );

  const clearLocal = useCallback(
    () =>
      setItems((prev) => {
        for (const file of prev) {
          if (file.url) {
            URL.revokeObjectURL(file.url);
          }
        }
        return [];
      }),
    [],
  );

  const add = usingProvider ? controller.attachments.add : addLocal;
  const remove = usingProvider ? controller.attachments.remove : removeLocal;
  const clear = usingProvider ? controller.attachments.clear : clearLocal;
  const openFileDialog = usingProvider
    ? controller.attachments.openFileDialog
    : openFileDialogLocal;

  const sanitizeIncomingFiles = useCallback(
    (fileList: File[] | FileList) => {
      const { accepted, message } = splitUnsupportedUploadFiles(fileList);
      if (message) {
        onError?.({
          code: "unsupported_package",
          message,
        });
        if (!onError) {
          toast.error(message);
        }
      }
      return accepted;
    },
    [onError],
  );

  // 向 Provider 暴露隐藏文件输入框，使外部菜单可以调用 openFileDialog()。
  useEffect(() => {
    if (!usingProvider) return;
    controller.__registerFileInput(inputRef, () => inputRef.current?.click());
  }, [usingProvider, controller]);

  // 出于安全原因，文件输入框不能通过脚本赋值。
  // syncHiddenInput 属性已不再生效。
  useEffect(() => {
    if (syncHiddenInput && inputRef.current && files.length === 0) {
      inputRef.current.value = "";
    }
  }, [files, syncHiddenInput]);

  // 按需在最近的表单和 document 上注册拖放处理器。
  useEffect(() => {
    const form = formRef.current;
    if (!form) return;
    if (globalDrop) return; // when global drop is on, let the document-level handler own drops

    const onDragOver = (e: DragEvent) => {
      if (e.dataTransfer?.types?.includes("Files")) {
        e.preventDefault();
      }
    };
    const onDrop = (e: DragEvent) => {
      if (e.dataTransfer?.types?.includes("Files")) {
        e.preventDefault();
      }
      if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
        const accepted = sanitizeIncomingFiles(e.dataTransfer.files);
        if (accepted.length > 0) {
          add(accepted);
        }
      }
    };
    form.addEventListener("dragover", onDragOver);
    form.addEventListener("drop", onDrop);
    return () => {
      form.removeEventListener("dragover", onDragOver);
      form.removeEventListener("drop", onDrop);
    };
  }, [add, globalDrop, sanitizeIncomingFiles]);

  useEffect(() => {
    if (!globalDrop) return;

    const onDragOver = (e: DragEvent) => {
      if (e.dataTransfer?.types?.includes("Files")) {
        e.preventDefault();
      }
    };
    const onDrop = (e: DragEvent) => {
      if (e.dataTransfer?.types?.includes("Files")) {
        e.preventDefault();
      }
      if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
        const accepted = sanitizeIncomingFiles(e.dataTransfer.files);
        if (accepted.length > 0) {
          add(accepted);
        }
      }
    };
    document.addEventListener("dragover", onDragOver);
    document.addEventListener("drop", onDrop);
    return () => {
      document.removeEventListener("dragover", onDragOver);
      document.removeEventListener("drop", onDrop);
    };
  }, [add, globalDrop, sanitizeIncomingFiles]);

  useEffect(
    () => () => {
      if (!usingProvider) {
        for (const f of filesRef.current) {
          if (f.url) URL.revokeObjectURL(f.url);
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅在卸载时清理；filesRef 始终指向最新值。
    [usingProvider],
  );

  const handleChange: ChangeEventHandler<HTMLInputElement> = (event) => {
    if (event.currentTarget.files) {
      const accepted = sanitizeIncomingFiles(event.currentTarget.files);
      if (accepted.length > 0) {
        add(accepted);
      }
    }
    // 重置输入值，以便再次选择先前已移除的文件。
    event.currentTarget.value = "";
  };

  const convertBlobUrlToDataUrl = async (
    url: string,
  ): Promise<string | null> => {
    try {
      const response = await fetch(url);
      const blob = await response.blob();
      return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result as string);
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(blob);
      });
    } catch {
      return null;
    }
  };

  const ctx = useMemo<AttachmentsContext>(
    () => ({
      files: files.map((item) => ({ ...item, id: item.id })),
      add,
      remove,
      clear,
      openFileDialog,
      fileInputRef: inputRef,
    }),
    [files, add, remove, clear, openFileDialog],
  );

  const handleSubmit: FormEventHandler<HTMLFormElement> = (event) => {
    event.preventDefault();

    const form = event.currentTarget;
    const text = usingProvider
      ? controller.textInput.value
      : (() => {
          const formData = new FormData(form);
          return (formData.get("message") as string) || "";
        })();

    // 捕获文本后立即重置表单，避免异步转换 Blob 时用户新输入被竞争条件丢失。
    if (!usingProvider) {
      form.reset();
    }

    // 异步将 Blob URL 转换为数据 URL。
    const submittedFileIds = files.map((file) => file.id);
    const clearSubmittedState = () => {
      const currentFileIds = new Set(filesRef.current.map((file) => file.id));
      const submittedFileIdsStillPresent = submittedFileIds.filter((id) =>
        currentFileIds.has(id),
      );
      if (submittedFileIdsStillPresent.length === filesRef.current.length) {
        clear();
      } else {
        for (const id of submittedFileIdsStillPresent) {
          remove(id);
        }
      }
      if (usingProvider && providerTextRef.current === text) {
        controller.textInput.clear();
      }
    };

    Promise.all(
      files.map(async ({ id, ...item }) => {
        if (item.file instanceof File) {
          // 下游上传准备逻辑直接读取保留的 File。
          return item;
        }
        if (item.url && item.url.startsWith("blob:")) {
          const dataUrl = await convertBlobUrlToDataUrl(item.url);
          // 转换失败时保留原始 Blob URL。
          return {
            ...item,
            url: dataUrl ?? item.url,
          };
        }
        return item;
      }),
    )
      .then((convertedFiles: PromptInputFilePart[]) => {
        try {
          const result = onSubmit({ text, files: convertedFiles }, event);

          // 同时处理同步和异步的 onSubmit。
          if (result instanceof Promise) {
            result
              .then(() => {
                clearSubmittedState();
              })
              .catch(() => {
                // 失败时不清空，用户可能需要重试。
              });
          } else {
            // 同步函数正常完成后清空附件。
            clearSubmittedState();
          }
        } catch {
          // 失败时不清空，用户可能需要重试。
        }
      })
      .catch(() => {
        // 失败时不清空，用户可能需要重试。
      });
  };

  // 根据是否需要本地 Provider 渲染。
  const inner = (
    <PromptInputValidationContext.Provider value={sanitizeIncomingFiles}>
      <input
        accept={accept}
        aria-label="Upload files"
        className="hidden"
        multiple={multiple}
        onChange={handleChange}
        ref={inputRef}
        title="Upload files"
        type="file"
      />
      <form
        className={cn("w-full", className)}
        onSubmit={handleSubmit}
        ref={formRef}
        {...props}
      >
        <InputGroup>{children}</InputGroup>
      </form>
    </PromptInputValidationContext.Provider>
  );

  return usingProvider ? (
    inner
  ) : (
    <LocalAttachmentsContext.Provider value={ctx}>
      {inner}
    </LocalAttachmentsContext.Provider>
  );
};

/** PromptInputBodyProps 的公开类型定义。 */
export type PromptInputBodyProps = HTMLAttributes<HTMLDivElement>;

/** PromptInputBody 组件：提供对应的界面结构与交互语义。 */
export const PromptInputBody = ({
  className,
  ...props
}: PromptInputBodyProps) => (
  <div className={cn("contents", className)} {...props} />
);

/** PromptInputTextareaProps 的公开类型定义。 */
export type PromptInputTextareaProps = ComponentProps<
  typeof InputGroupTextarea
>;

/** PromptInputTextarea 组件：提供对应的界面结构与交互语义。 */
export const PromptInputTextarea = ({
  onChange,
  onKeyDown,
  className,
  placeholder = "What would you like to know?",
  ...props
}: PromptInputTextareaProps) => {
  const controller = useOptionalPromptInputController();
  const attachments = usePromptInputAttachments();
  const sanitizeIncomingFiles = usePromptInputValidation();
  const [isComposing, setIsComposing] = useState(false);

  const handleKeyDown: KeyboardEventHandler<HTMLTextAreaElement> = (e) => {
    onKeyDown?.(e);
    if (e.defaultPrevented) {
      return;
    }
    if (e.key === "Enter") {
      if (isIMEComposing(e, isComposing)) {
        return;
      }
      if (e.shiftKey) {
        return;
      }
      e.preventDefault();

      // 提交前检查提交按钮是否已禁用。
      const form = e.currentTarget.form;
      const submitButton = form?.querySelector(
        'button[type="submit"]',
      ) as HTMLButtonElement | null;
      if (submitButton?.disabled) {
        return;
      }

      form?.requestSubmit();
    }
  };

  const handlePaste: ClipboardEventHandler<HTMLTextAreaElement> = (event) => {
    const items = event.clipboardData?.items;

    if (!items) {
      return;
    }

    const files: File[] = [];

    for (const item of items) {
      if (item.kind === "file") {
        const file = item.getAsFile();
        if (file) {
          files.push(file);
        }
      }
    }

    if (files.length > 0) {
      event.preventDefault();
      const accepted = sanitizeIncomingFiles
        ? sanitizeIncomingFiles(files)
        : files;
      if (accepted.length > 0) {
        attachments.add(accepted);
      }
    }
  };

  const controlledProps = controller
    ? {
        value: controller.textInput.value,
        onChange: (e: ChangeEvent<HTMLTextAreaElement>) => {
          controller.textInput.setInput(e.currentTarget.value);
          onChange?.(e);
        },
      }
    : {
        onChange,
      };

  return (
    <InputGroupTextarea
      className={cn("field-sizing-content max-h-48 min-h-16", className)}
      name="message"
      onCompositionEnd={() => setIsComposing(false)}
      onCompositionStart={() => setIsComposing(true)}
      onKeyDown={handleKeyDown}
      onPaste={handlePaste}
      placeholder={placeholder}
      {...props}
      {...controlledProps}
    />
  );
};

/** PromptInputHeaderProps 的公开类型定义。 */
export type PromptInputHeaderProps = Omit<
  ComponentProps<typeof InputGroupAddon>,
  "align"
>;

/** PromptInputHeader 组件：提供对应的界面结构与交互语义。 */
export const PromptInputHeader = ({
  className,
  ...props
}: PromptInputHeaderProps) => (
  <InputGroupAddon
    align="block-end"
    className={cn("order-first flex-wrap gap-1", className)}
    {...props}
  />
);

/** PromptInputFooterProps 的公开类型定义。 */
export type PromptInputFooterProps = Omit<
  ComponentProps<typeof InputGroupAddon>,
  "align"
>;

/** PromptInputFooter 组件：提供对应的界面结构与交互语义。 */
export const PromptInputFooter = ({
  className,
  ...props
}: PromptInputFooterProps) => (
  <InputGroupAddon
    align="block-end"
    className={cn("justify-between gap-1", className)}
    {...props}
  />
);

/** PromptInputToolsProps 的公开类型定义。 */
export type PromptInputToolsProps = HTMLAttributes<HTMLDivElement>;

/** PromptInputTools 组件：提供对应的界面结构与交互语义。 */
export const PromptInputTools = ({
  className,
  ...props
}: PromptInputToolsProps) => (
  <div className={cn("flex items-center gap-1", className)} {...props} />
);

/** PromptInputButtonProps 的公开类型定义。 */
export type PromptInputButtonProps = ComponentProps<typeof InputGroupButton>;

/** PromptInputButton 组件：提供对应的界面结构与交互语义。 */
export const PromptInputButton = ({
  variant = "ghost",
  className,
  size,
  ...props
}: PromptInputButtonProps) => {
  return (
    <InputGroupButton
      className={cn(className)}
      size="sm"
      type="button"
      variant={variant}
      {...props}
    />
  );
};

/** PromptInputActionMenuProps 的公开类型定义。 */
export type PromptInputActionMenuProps = ComponentProps<typeof DropdownMenu>;
/** PromptInputActionMenu 组件：提供对应的界面结构与交互语义。 */
export const PromptInputActionMenu = (props: PromptInputActionMenuProps) => (
  <DropdownMenu {...props} />
);

/** PromptInputActionMenuTriggerProps 的公开类型定义。 */
export type PromptInputActionMenuTriggerProps = PromptInputButtonProps;

/** PromptInputActionMenuTrigger 组件：提供对应的界面结构与交互语义。 */
export const PromptInputActionMenuTrigger = ({
  className,
  children,
  ...props
}: PromptInputActionMenuTriggerProps) => (
  <DropdownMenuTrigger asChild>
    <PromptInputButton className={className} {...props}>
      {children ?? <PlusIcon className="size-4" />}
    </PromptInputButton>
  </DropdownMenuTrigger>
);

/** PromptInputActionMenuContentProps 的公开类型定义。 */
export type PromptInputActionMenuContentProps = ComponentProps<
  typeof DropdownMenuContent
>;
/** PromptInputActionMenuContent 组件：提供对应的界面结构与交互语义。 */
export const PromptInputActionMenuContent = ({
  className,
  ...props
}: PromptInputActionMenuContentProps) => (
  <DropdownMenuContent align="start" className={cn(className)} {...props} />
);

/** PromptInputActionMenuItemProps 的公开类型定义。 */
export type PromptInputActionMenuItemProps = ComponentProps<
  typeof DropdownMenuItem
>;
/** PromptInputActionMenuItem 组件：提供对应的界面结构与交互语义。 */
export const PromptInputActionMenuItem = ({
  className,
  ...props
}: PromptInputActionMenuItemProps) => (
  <DropdownMenuItem className={cn(className)} {...props} />
);

// 注意：打开文件对话框等具有副作用的操作由按需启用的模块提供（如 prompt-input-attachments）。

/** PromptInputSubmitProps 的公开类型定义。 */
export type PromptInputSubmitProps = ComponentProps<typeof InputGroupButton> & {
  status?: ChatStatus;
};

/** PromptInputSubmit 组件：提供对应的界面结构与交互语义。 */
export const PromptInputSubmit = ({
  className,
  variant = "default",
  size = "icon-sm",
  status,
  children,
  ...props
}: PromptInputSubmitProps) => {
  let Icon = <ArrowUpIcon className="size-4" />;

  if (status === "submitted") {
    Icon = <Loader2Icon className="size-4 animate-spin" />;
  } else if (status === "streaming") {
    Icon = <SquareIcon className="size-4" />;
  } else if (status === "error") {
    Icon = <XIcon className="size-4" />;
  }

  return (
    <InputGroupButton
      aria-label="Submit"
      className={cn(className)}
      size={size}
      type="submit"
      variant={variant}
      {...props}
    >
      {children ?? Icon}
    </InputGroupButton>
  );
};

interface SpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  stop(): void;
  onstart: ((this: SpeechRecognition, ev: Event) => any) | null;
  onend: ((this: SpeechRecognition, ev: Event) => any) | null;
  onresult:
    | ((this: SpeechRecognition, ev: SpeechRecognitionEvent) => any)
    | null;
  onerror:
    | ((this: SpeechRecognition, ev: SpeechRecognitionErrorEvent) => any)
    | null;
}

interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList;
  resultIndex: number;
}

type SpeechRecognitionResultList = {
  readonly length: number;
  item(index: number): SpeechRecognitionResult;
  [index: number]: SpeechRecognitionResult;
};

type SpeechRecognitionResult = {
  readonly length: number;
  item(index: number): SpeechRecognitionAlternative;
  [index: number]: SpeechRecognitionAlternative;
  isFinal: boolean;
};

type SpeechRecognitionAlternative = {
  transcript: string;
  confidence: number;
};

interface SpeechRecognitionErrorEvent extends Event {
  error: string;
}

declare global {
  interface Window {
    SpeechRecognition: {
      new (): SpeechRecognition;
    };
    webkitSpeechRecognition: {
      new (): SpeechRecognition;
    };
  }
}

/** PromptInputSpeechButtonProps 的公开类型定义。 */
export type PromptInputSpeechButtonProps = ComponentProps<
  typeof PromptInputButton
> & {
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
  onTranscriptionChange?: (text: string) => void;
};

/** PromptInputSpeechButton 组件：提供对应的界面结构与交互语义。 */
export const PromptInputSpeechButton = ({
  className,
  textareaRef,
  onTranscriptionChange,
  ...props
}: PromptInputSpeechButtonProps) => {
  const [isListening, setIsListening] = useState(false);
  const [recognition, setRecognition] = useState<SpeechRecognition | null>(
    null,
  );
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const callbacksRef = useRef({ textareaRef, onTranscriptionChange });
  callbacksRef.current = { textareaRef, onTranscriptionChange };

  useEffect(() => {
    if (
      typeof window !== "undefined" &&
      ("SpeechRecognition" in window || "webkitSpeechRecognition" in window)
    ) {
      const SpeechRecognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;
      const speechRecognition = new SpeechRecognition();

      speechRecognition.continuous = true;
      speechRecognition.interimResults = true;
      speechRecognition.lang = "en-US";

      speechRecognition.onstart = () => {
        setIsListening(true);
      };

      speechRecognition.onend = () => {
        setIsListening(false);
      };

      speechRecognition.onresult = (event) => {
        let finalTranscript = "";

        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          if (result?.isFinal) {
            finalTranscript += result[0]?.transcript ?? "";
          }
        }

        const currentTextareaRef = callbacksRef.current.textareaRef;
        const currentOnTranscriptionChange =
          callbacksRef.current.onTranscriptionChange;

        if (finalTranscript && currentTextareaRef?.current) {
          const textarea = currentTextareaRef.current;
          const currentValue = textarea.value;
          const newValue =
            currentValue + (currentValue ? " " : "") + finalTranscript;

          textarea.value = newValue;
          textarea.dispatchEvent(new Event("input", { bubbles: true }));
          currentOnTranscriptionChange?.(newValue);
        }
      };

      speechRecognition.onerror = (event) => {
        console.error("Speech recognition error:", event.error);
        setIsListening(false);
      };

      recognitionRef.current = speechRecognition;
      setRecognition(speechRecognition);
    }

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
    };
  }, []);

  const toggleListening = useCallback(() => {
    if (!recognition) {
      return;
    }

    if (isListening) {
      recognition.stop();
    } else {
      recognition.start();
    }
  }, [recognition, isListening]);

  return (
    <PromptInputButton
      className={cn(
        "relative transition-all duration-200",
        isListening && "bg-accent text-accent-foreground animate-pulse",
        className,
      )}
      disabled={!recognition}
      onClick={toggleListening}
      {...props}
    >
      <MicIcon className="size-4" />
    </PromptInputButton>
  );
};

/** PromptInputSelectProps 的公开类型定义。 */
export type PromptInputSelectProps = ComponentProps<typeof Select>;

/** PromptInputSelect 组件：提供对应的界面结构与交互语义。 */
export const PromptInputSelect = (props: PromptInputSelectProps) => (
  <Select {...props} />
);

/** PromptInputSelectTriggerProps 的公开类型定义。 */
export type PromptInputSelectTriggerProps = ComponentProps<
  typeof SelectTrigger
>;

/** PromptInputSelectTrigger 组件：提供对应的界面结构与交互语义。 */
export const PromptInputSelectTrigger = ({
  className,
  ...props
}: PromptInputSelectTriggerProps) => (
  <SelectTrigger
    className={cn(
      "text-muted-foreground border-none bg-transparent font-medium shadow-none transition-colors",
      "hover:bg-accent hover:text-foreground aria-expanded:bg-accent aria-expanded:text-foreground",
      className,
    )}
    {...props}
  />
);

/** PromptInputSelectContentProps 的公开类型定义。 */
export type PromptInputSelectContentProps = ComponentProps<
  typeof SelectContent
>;

/** PromptInputSelectContent 组件：提供对应的界面结构与交互语义。 */
export const PromptInputSelectContent = ({
  className,
  ...props
}: PromptInputSelectContentProps) => (
  <SelectContent className={cn(className)} {...props} />
);

/** PromptInputSelectItemProps 的公开类型定义。 */
export type PromptInputSelectItemProps = ComponentProps<typeof SelectItem>;

/** PromptInputSelectItem 组件：提供对应的界面结构与交互语义。 */
export const PromptInputSelectItem = ({
  className,
  ...props
}: PromptInputSelectItemProps) => (
  <SelectItem className={cn(className)} {...props} />
);

/** PromptInputSelectValueProps 的公开类型定义。 */
export type PromptInputSelectValueProps = ComponentProps<typeof SelectValue>;

/** PromptInputSelectValue 组件：提供对应的界面结构与交互语义。 */
export const PromptInputSelectValue = ({
  className,
  ...props
}: PromptInputSelectValueProps) => (
  <SelectValue className={cn(className)} {...props} />
);

/** PromptInputHoverCardProps 的公开类型定义。 */
export type PromptInputHoverCardProps = ComponentProps<typeof HoverCard>;

/** PromptInputHoverCard 组件：提供对应的界面结构与交互语义。 */
export const PromptInputHoverCard = ({
  openDelay = 0,
  closeDelay = 0,
  ...props
}: PromptInputHoverCardProps) => (
  <HoverCard closeDelay={closeDelay} openDelay={openDelay} {...props} />
);

/** PromptInputHoverCardTriggerProps 的公开类型定义。 */
export type PromptInputHoverCardTriggerProps = ComponentProps<
  typeof HoverCardTrigger
>;

/** PromptInputHoverCardTrigger 组件：提供对应的界面结构与交互语义。 */
export const PromptInputHoverCardTrigger = (
  props: PromptInputHoverCardTriggerProps,
) => <HoverCardTrigger {...props} />;

/** PromptInputHoverCardContentProps 的公开类型定义。 */
export type PromptInputHoverCardContentProps = ComponentProps<
  typeof HoverCardContent
>;

/** PromptInputHoverCardContent 组件：提供对应的界面结构与交互语义。 */
export const PromptInputHoverCardContent = ({
  align = "start",
  ...props
}: PromptInputHoverCardContentProps) => (
  <HoverCardContent align={align} {...props} />
);

/** PromptInputTabsListProps 的公开类型定义。 */
export type PromptInputTabsListProps = HTMLAttributes<HTMLDivElement>;

/** PromptInputTabsList 组件：提供对应的界面结构与交互语义。 */
export const PromptInputTabsList = ({
  className,
  ...props
}: PromptInputTabsListProps) => <div className={cn(className)} {...props} />;

/** PromptInputTabProps 的公开类型定义。 */
export type PromptInputTabProps = HTMLAttributes<HTMLDivElement>;

/** PromptInputTab 组件：提供对应的界面结构与交互语义。 */
export const PromptInputTab = ({
  className,
  ...props
}: PromptInputTabProps) => <div className={cn(className)} {...props} />;

/** PromptInputTabLabelProps 的公开类型定义。 */
export type PromptInputTabLabelProps = HTMLAttributes<HTMLHeadingElement>;

/** PromptInputTabLabel 组件：提供对应的界面结构与交互语义。 */
export const PromptInputTabLabel = ({
  className,
  ...props
}: PromptInputTabLabelProps) => (
  <h3
    className={cn(
      "text-muted-foreground mb-2 px-3 text-xs font-medium",
      className,
    )}
    {...props}
  />
);

/** PromptInputTabBodyProps 的公开类型定义。 */
export type PromptInputTabBodyProps = HTMLAttributes<HTMLDivElement>;

/** PromptInputTabBody 组件：提供对应的界面结构与交互语义。 */
export const PromptInputTabBody = ({
  className,
  ...props
}: PromptInputTabBodyProps) => (
  <div className={cn("space-y-1", className)} {...props} />
);

/** PromptInputTabItemProps 的公开类型定义。 */
export type PromptInputTabItemProps = HTMLAttributes<HTMLDivElement>;

/** PromptInputTabItem 组件：提供对应的界面结构与交互语义。 */
export const PromptInputTabItem = ({
  className,
  ...props
}: PromptInputTabItemProps) => (
  <div
    className={cn(
      "hover:bg-accent flex items-center gap-2 px-3 py-2 text-xs",
      className,
    )}
    {...props}
  />
);

/** PromptInputCommandProps 的公开类型定义。 */
export type PromptInputCommandProps = ComponentProps<typeof Command>;

/** PromptInputCommand 组件：提供对应的界面结构与交互语义。 */
export const PromptInputCommand = ({
  className,
  ...props
}: PromptInputCommandProps) => <Command className={cn(className)} {...props} />;

/** PromptInputCommandInputProps 的公开类型定义。 */
export type PromptInputCommandInputProps = ComponentProps<typeof CommandInput>;

/** PromptInputCommandInput 组件：提供对应的界面结构与交互语义。 */
export const PromptInputCommandInput = ({
  className,
  ...props
}: PromptInputCommandInputProps) => (
  <CommandInput className={cn(className)} {...props} />
);

/** PromptInputCommandListProps 的公开类型定义。 */
export type PromptInputCommandListProps = ComponentProps<typeof CommandList>;

/** PromptInputCommandList 组件：提供对应的界面结构与交互语义。 */
export const PromptInputCommandList = ({
  className,
  ...props
}: PromptInputCommandListProps) => (
  <CommandList className={cn(className)} {...props} />
);

/** PromptInputCommandEmptyProps 的公开类型定义。 */
export type PromptInputCommandEmptyProps = ComponentProps<typeof CommandEmpty>;

/** PromptInputCommandEmpty 组件：提供对应的界面结构与交互语义。 */
export const PromptInputCommandEmpty = ({
  className,
  ...props
}: PromptInputCommandEmptyProps) => (
  <CommandEmpty className={cn(className)} {...props} />
);

/** PromptInputCommandGroupProps 的公开类型定义。 */
export type PromptInputCommandGroupProps = ComponentProps<typeof CommandGroup>;

/** PromptInputCommandGroup 组件：提供对应的界面结构与交互语义。 */
export const PromptInputCommandGroup = ({
  className,
  ...props
}: PromptInputCommandGroupProps) => (
  <CommandGroup className={cn(className)} {...props} />
);

/** PromptInputCommandItemProps 的公开类型定义。 */
export type PromptInputCommandItemProps = ComponentProps<typeof CommandItem>;

/** PromptInputCommandItem 组件：提供对应的界面结构与交互语义。 */
export const PromptInputCommandItem = ({
  className,
  ...props
}: PromptInputCommandItemProps) => (
  <CommandItem className={cn(className)} {...props} />
);

/** PromptInputCommandSeparatorProps 的公开类型定义。 */
export type PromptInputCommandSeparatorProps = ComponentProps<
  typeof CommandSeparator
>;

/** PromptInputCommandSeparator 组件：提供对应的界面结构与交互语义。 */
export const PromptInputCommandSeparator = ({
  className,
  ...props
}: PromptInputCommandSeparatorProps) => (
  <CommandSeparator className={cn(className)} {...props} />
);
