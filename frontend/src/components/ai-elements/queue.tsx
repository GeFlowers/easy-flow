"use client";

import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ScrollArea } from "@/components/ui/scroll-area";

import { ChevronDownIcon, PaperclipIcon } from "lucide-react";
import type { ComponentProps } from "react";

export type QueueMessagePart = {
  type: string;
  text?: string;
  url?: string;
  filename?: string;
  mediaType?: string;
};

export type QueueMessage = {
  id: string;
  parts: QueueMessagePart[];
};

export type QueueTodo = {
  id: string;
  title: string;
  description?: string;
  status?: "pending" | "completed";
};

export type QueueItemProps = ComponentProps<"li">;

/** 用于排列单条待发送消息或待办内容的列表项容器。 */
export const QueueItem = ({ className, ...props }: QueueItemProps) => (
  <li
    className={[
      "group hover:bg-muted flex flex-col gap-1 rounded-md px-3 py-1 text-sm transition-colors",
      className,
    ]
      .filter(Boolean)
      .join(" ")}
    {...props}
  />
);

export type QueueItemIndicatorProps = ComponentProps<"span"> & {
  completed?: boolean;
};

/** 以实心浅色或空心圆点区分已完成与待处理项目。 */
export const QueueItemIndicator = ({
  completed = false,
  className,
  ...props
}: QueueItemIndicatorProps) => (
  <span
    className={[
      "mt-0.5 inline-block size-2.5 rounded-full border",
      completed
        ? "border-muted-foreground/20 bg-muted-foreground/10"
        : "border-muted-foreground/50",
      className,
    ]
      .filter(Boolean)
      .join(" ")}
    {...props}
  />
);

export type QueueItemContentProps = ComponentProps<"span"> & {
  completed?: boolean;
};

/** 展示项目主文本；完成后降低对比度并添加删除线。 */
export const QueueItemContent = ({
  completed = false,
  className,
  ...props
}: QueueItemContentProps) => (
  <span
    className={[
      "line-clamp-1 grow break-words",
      completed
        ? "text-muted-foreground/50 line-through"
        : "text-muted-foreground",
      className,
    ]
      .filter(Boolean)
      .join(" ")}
    {...props}
  />
);

export type QueueItemDescriptionProps = ComponentProps<"div"> & {
  completed?: boolean;
};

/** 展示相对主文本缩进的补充说明，并同步已完成状态的弱化样式。 */
export const QueueItemDescription = ({
  completed = false,
  className,
  ...props
}: QueueItemDescriptionProps) => (
  <div
    className={[
      "ml-6 text-xs",
      completed
        ? "text-muted-foreground/40 line-through"
        : "text-muted-foreground",
      className,
    ]
      .filter(Boolean)
      .join(" ")}
    {...props}
  />
);

export type QueueItemActionsProps = ComponentProps<"div">;

/** 将项目上的辅助按钮并排放置，供悬停操作区组合使用。 */
export const QueueItemActions = ({
  className,
  ...props
}: QueueItemActionsProps) => (
  <div
    className={["flex gap-1", className].filter(Boolean).join(" ")}
    {...props}
  />
);

export type QueueItemActionProps = Omit<
  ComponentProps<typeof Button>,
  "variant" | "size"
>;

/** 项目专用的幽灵图标按钮，默认隐藏并在悬停列表项时显现。 */
export const QueueItemAction = ({
  className,
  ...props
}: QueueItemActionProps) => (
  <Button
    className={[
      "text-muted-foreground hover:bg-muted-foreground/10 hover:text-foreground size-auto rounded p-1 opacity-0 transition-opacity group-hover:opacity-100",
      className,
    ]
      .filter(Boolean)
      .join(" ")}
    size="icon"
    type="button"
    variant="ghost"
    {...props}
  />
);

export type QueueItemAttachmentProps = ComponentProps<"div">;

/** 将待发送项目的附件缩略图和文件标签按行排列。 */
export const QueueItemAttachment = ({
  className,
  ...props
}: QueueItemAttachmentProps) => (
  <div
    className={["mt-1 flex flex-wrap gap-2", className]
      .filter(Boolean)
      .join(" ")}
    {...props}
  />
);

export type QueueItemImageProps = ComponentProps<"img">;

/** 以固定尺寸缩略图展示图片附件，并隐藏非必要替代文本。 */
export const QueueItemImage = ({
  className,
  ...props
}: QueueItemImageProps) => (
  <img
    alt=""
    className={["h-8 w-8 rounded border object-cover", className]
      .filter(Boolean)
      .join(" ")}
    height={32}
    width={32}
    {...props}
  />
);

export type QueueItemFileProps = ComponentProps<"span">;

/** 显示带回形针标识的文件标签，并截断过长文件名。 */
export const QueueItemFile = ({
  children,
  className,
  ...props
}: QueueItemFileProps) => (
  <span
    className={[
      "bg-muted flex items-center gap-1 rounded border px-2 py-1 text-xs",
      className,
    ]
      .filter(Boolean)
      .join(" ")}
    {...props}
  >
    <PaperclipIcon size={12} />
    <span className="max-w-[100px] truncate">{children}</span>
  </span>
);

export type QueueListProps = ComponentProps<typeof ScrollArea>;

/** 在限定最大高度的滚动区域中展示队列项目列表。 */
export const QueueList = ({
  children,
  className,
  ...props
}: QueueListProps) => (
  <ScrollArea
    className={["mt-2 -mb-1", className].filter(Boolean).join(" ")}
    {...props}
  >
    <div className="max-h-40 pr-4">
      <ul>{children}</ul>
    </div>
  </ScrollArea>
);

// QueueSection：可折叠分区容器。
export type QueueSectionProps = ComponentProps<typeof Collapsible>;

/** 提供可控制默认展开状态的折叠分区根节点。 */
export const QueueSection = ({
  className,
  defaultOpen = true,
  ...props
}: QueueSectionProps) => (
  <Collapsible
    className={[className].filter(Boolean).join(" ")}
    defaultOpen={defaultOpen}
    {...props}
  />
);

// QueueSectionTrigger：分区标题与触发器。
export type QueueSectionTriggerProps = ComponentProps<"button">;

/** 包装分区标题按钮，并通过折叠控件切换内容显隐。 */
export const QueueSectionTrigger = ({
  children,
  className,
  ...props
}: QueueSectionTriggerProps) => (
  <CollapsibleTrigger asChild>
    <button
      className={[
        "group bg-muted/40 text-muted-foreground hover:bg-muted flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm font-medium transition-colors",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      type="button"
      {...props}
    >
      {children}
    </button>
  </CollapsibleTrigger>
);

// QueueSectionLabel：含图标和数量的标签内容。
export type QueueSectionLabelProps = ComponentProps<"span"> & {
  count?: number;
  label: string;
  icon?: React.ReactNode;
};

/** 组合展开指示符、可选图标、项目数量和分区名称。 */
export const QueueSectionLabel = ({
  count,
  label,
  icon,
  className,
  ...props
}: QueueSectionLabelProps) => (
  <span
    className={["flex items-center gap-2", className].filter(Boolean).join(" ")}
    {...props}
  >
    <ChevronDownIcon className="size-4 transition-transform group-data-[state=closed]:-rotate-90" />
    {icon}
    <span>
      {count} {label}
    </span>
  </span>
);

// QueueSectionContent：可折叠内容区域。
export type QueueSectionContentProps = ComponentProps<
  typeof CollapsibleContent
>;

/** 将分区子项接入折叠面板内容区域。 */
export const QueueSectionContent = ({
  className,
  ...props
}: QueueSectionContentProps) => (
  <CollapsibleContent
    className={[className].filter(Boolean).join(" ")}
    {...props}
  />
);

export type QueueProps = ComponentProps<"div">;

/** 为消息队列或待办列表提供统一边框、间距和背景的外层容器。 */
export const Queue = ({ className, ...props }: QueueProps) => (
  <div
    className={[
      "border-border bg-background flex flex-col gap-2 rounded-xl border px-3 pt-2 pb-2 shadow-xs",
      className,
    ]
      .filter(Boolean)
      .join(" ")}
    {...props}
  />
);
