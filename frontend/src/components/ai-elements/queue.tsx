"use client";

import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { ChevronDownIcon, PaperclipIcon } from "lucide-react";
import type { ComponentProps } from "react";

/** QueueMessagePart 的公开类型定义。 */
export type QueueMessagePart = {
  type: string;
  text?: string;
  url?: string;
  filename?: string;
  mediaType?: string;
};

/** QueueMessage 的公开类型定义。 */
export type QueueMessage = {
  id: string;
  parts: QueueMessagePart[];
};

/** QueueTodo 的公开类型定义。 */
export type QueueTodo = {
  id: string;
  title: string;
  description?: string;
  status?: "pending" | "completed";
};

/** QueueItemProps 的公开类型定义。 */
export type QueueItemProps = ComponentProps<"li">;

/** QueueItem 组件：提供对应的界面结构与交互语义。 */
export const QueueItem = ({ className, ...props }: QueueItemProps) => (
  <li
    className={cn(
      "group hover:bg-muted flex flex-col gap-1 rounded-md px-3 py-1 text-sm transition-colors",
      className,
    )}
    {...props}
  />
);

/** QueueItemIndicatorProps 的公开类型定义。 */
export type QueueItemIndicatorProps = ComponentProps<"span"> & {
  completed?: boolean;
};

/** QueueItemIndicator 组件：提供对应的界面结构与交互语义。 */
export const QueueItemIndicator = ({
  completed = false,
  className,
  ...props
}: QueueItemIndicatorProps) => (
  <span
    className={cn(
      "mt-0.5 inline-block size-2.5 rounded-full border",
      completed
        ? "border-muted-foreground/20 bg-muted-foreground/10"
        : "border-muted-foreground/50",
      className,
    )}
    {...props}
  />
);

/** QueueItemContentProps 的公开类型定义。 */
export type QueueItemContentProps = ComponentProps<"span"> & {
  completed?: boolean;
};

/** QueueItemContent 组件：提供对应的界面结构与交互语义。 */
export const QueueItemContent = ({
  completed = false,
  className,
  ...props
}: QueueItemContentProps) => (
  <span
    className={cn(
      "line-clamp-1 grow break-words",
      completed
        ? "text-muted-foreground/50 line-through"
        : "text-muted-foreground",
      className,
    )}
    {...props}
  />
);

/** QueueItemDescriptionProps 的公开类型定义。 */
export type QueueItemDescriptionProps = ComponentProps<"div"> & {
  completed?: boolean;
};

/** QueueItemDescription 组件：提供对应的界面结构与交互语义。 */
export const QueueItemDescription = ({
  completed = false,
  className,
  ...props
}: QueueItemDescriptionProps) => (
  <div
    className={cn(
      "ml-6 text-xs",
      completed
        ? "text-muted-foreground/40 line-through"
        : "text-muted-foreground",
      className,
    )}
    {...props}
  />
);

/** QueueItemActionsProps 的公开类型定义。 */
export type QueueItemActionsProps = ComponentProps<"div">;

/** QueueItemActions 组件：提供对应的界面结构与交互语义。 */
export const QueueItemActions = ({
  className,
  ...props
}: QueueItemActionsProps) => (
  <div className={cn("flex gap-1", className)} {...props} />
);

/** QueueItemActionProps 的公开类型定义。 */
export type QueueItemActionProps = Omit<
  ComponentProps<typeof Button>,
  "variant" | "size"
>;

/** QueueItemAction 组件：提供对应的界面结构与交互语义。 */
export const QueueItemAction = ({
  className,
  ...props
}: QueueItemActionProps) => (
  <Button
    className={cn(
      "text-muted-foreground hover:bg-muted-foreground/10 hover:text-foreground size-auto rounded p-1 opacity-0 transition-opacity group-hover:opacity-100",
      className,
    )}
    size="icon"
    type="button"
    variant="ghost"
    {...props}
  />
);

/** QueueItemAttachmentProps 的公开类型定义。 */
export type QueueItemAttachmentProps = ComponentProps<"div">;

/** QueueItemAttachment 组件：提供对应的界面结构与交互语义。 */
export const QueueItemAttachment = ({
  className,
  ...props
}: QueueItemAttachmentProps) => (
  <div className={cn("mt-1 flex flex-wrap gap-2", className)} {...props} />
);

/** QueueItemImageProps 的公开类型定义。 */
export type QueueItemImageProps = ComponentProps<"img">;

/** QueueItemImage 组件：提供对应的界面结构与交互语义。 */
export const QueueItemImage = ({
  className,
  ...props
}: QueueItemImageProps) => (
  <img
    alt=""
    className={cn("h-8 w-8 rounded border object-cover", className)}
    height={32}
    width={32}
    {...props}
  />
);

/** QueueItemFileProps 的公开类型定义。 */
export type QueueItemFileProps = ComponentProps<"span">;

/** QueueItemFile 组件：提供对应的界面结构与交互语义。 */
export const QueueItemFile = ({
  children,
  className,
  ...props
}: QueueItemFileProps) => (
  <span
    className={cn(
      "bg-muted flex items-center gap-1 rounded border px-2 py-1 text-xs",
      className,
    )}
    {...props}
  >
    <PaperclipIcon size={12} />
    <span className="max-w-[100px] truncate">{children}</span>
  </span>
);

/** QueueListProps 的公开类型定义。 */
export type QueueListProps = ComponentProps<typeof ScrollArea>;

/** QueueList 组件：提供对应的界面结构与交互语义。 */
export const QueueList = ({
  children,
  className,
  ...props
}: QueueListProps) => (
  <ScrollArea className={cn("mt-2 -mb-1", className)} {...props}>
    <div className="max-h-40 pr-4">
      <ul>{children}</ul>
    </div>
  </ScrollArea>
);

// QueueSection：可折叠分区容器。
/** QueueSectionProps 的公开类型定义。 */
export type QueueSectionProps = ComponentProps<typeof Collapsible>;

/** QueueSection 组件：提供对应的界面结构与交互语义。 */
export const QueueSection = ({
  className,
  defaultOpen = true,
  ...props
}: QueueSectionProps) => (
  <Collapsible className={cn(className)} defaultOpen={defaultOpen} {...props} />
);

// QueueSectionTrigger：分区标题与触发器。
/** QueueSectionTriggerProps 的公开类型定义。 */
export type QueueSectionTriggerProps = ComponentProps<"button">;

/** QueueSectionTrigger 组件：提供对应的界面结构与交互语义。 */
export const QueueSectionTrigger = ({
  children,
  className,
  ...props
}: QueueSectionTriggerProps) => (
  <CollapsibleTrigger asChild>
    <button
      className={cn(
        "group bg-muted/40 text-muted-foreground hover:bg-muted flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm font-medium transition-colors",
        className,
      )}
      type="button"
      {...props}
    >
      {children}
    </button>
  </CollapsibleTrigger>
);

// QueueSectionLabel：含图标和数量的标签内容。
/** QueueSectionLabelProps 的公开类型定义。 */
export type QueueSectionLabelProps = ComponentProps<"span"> & {
  count?: number;
  label: string;
  icon?: React.ReactNode;
};

/** QueueSectionLabel 组件：提供对应的界面结构与交互语义。 */
export const QueueSectionLabel = ({
  count,
  label,
  icon,
  className,
  ...props
}: QueueSectionLabelProps) => (
  <span className={cn("flex items-center gap-2", className)} {...props}>
    <ChevronDownIcon className="size-4 transition-transform group-data-[state=closed]:-rotate-90" />
    {icon}
    <span>
      {count} {label}
    </span>
  </span>
);

// QueueSectionContent：可折叠内容区域。
/** QueueSectionContentProps 的公开类型定义。 */
export type QueueSectionContentProps = ComponentProps<
  typeof CollapsibleContent
>;

/** QueueSectionContent 组件：提供对应的界面结构与交互语义。 */
export const QueueSectionContent = ({
  className,
  ...props
}: QueueSectionContentProps) => (
  <CollapsibleContent className={cn(className)} {...props} />
);

/** QueueProps 的公开类型定义。 */
export type QueueProps = ComponentProps<"div">;

/** Queue 组件：提供对应的界面结构与交互语义。 */
export const Queue = ({ className, ...props }: QueueProps) => (
  <div
    className={cn(
      "border-border bg-background flex flex-col gap-2 rounded-xl border px-3 pt-2 pb-2 shadow-xs",
      className,
    )}
    {...props}
  />
);
