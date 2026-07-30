"use client";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { ChevronDownIcon, SearchIcon } from "lucide-react";
import type { ComponentProps } from "react";

/** TaskItemFileProps 的公开类型定义。 */
export type TaskItemFileProps = ComponentProps<"div">;

/** TaskItemFile 组件：提供对应的界面结构与交互语义。 */
export const TaskItemFile = ({
  children,
  className,
  ...props
}: TaskItemFileProps) => (
  <div
    className={cn(
      "bg-secondary text-foreground inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs",
      className,
    )}
    {...props}
  >
    {children}
  </div>
);

/** TaskItemProps 的公开类型定义。 */
export type TaskItemProps = ComponentProps<"div">;

/** TaskItem 组件：提供对应的界面结构与交互语义。 */
export const TaskItem = ({ children, className, ...props }: TaskItemProps) => (
  <div className={cn("text-muted-foreground text-sm", className)} {...props}>
    {children}
  </div>
);

/** TaskProps 的公开类型定义。 */
export type TaskProps = ComponentProps<typeof Collapsible>;

/** Task 组件：提供对应的界面结构与交互语义。 */
export const Task = ({
  defaultOpen = true,
  className,
  ...props
}: TaskProps) => (
  <Collapsible className={cn(className)} defaultOpen={defaultOpen} {...props} />
);

/** TaskTriggerProps 的公开类型定义。 */
export type TaskTriggerProps = ComponentProps<typeof CollapsibleTrigger> & {
  title: string;
};

/** TaskTrigger 组件：提供对应的界面结构与交互语义。 */
export const TaskTrigger = ({
  children,
  className,
  title,
  ...props
}: TaskTriggerProps) => (
  <CollapsibleTrigger asChild className={cn("group", className)} {...props}>
    {children ?? (
      <div className="text-muted-foreground hover:text-foreground flex w-full cursor-pointer items-center gap-2 text-sm transition-colors">
        <SearchIcon className="size-4" />
        <p className="text-sm">{title}</p>
        <ChevronDownIcon className="size-4 transition-transform group-data-[state=open]:rotate-180" />
      </div>
    )}
  </CollapsibleTrigger>
);

/** TaskContentProps 的公开类型定义。 */
export type TaskContentProps = ComponentProps<typeof CollapsibleContent>;

/** TaskContent 组件：提供对应的界面结构与交互语义。 */
export const TaskContent = ({
  children,
  className,
  ...props
}: TaskContentProps) => (
  <CollapsibleContent
    className={cn(
      "data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-top-2 data-[state=open]:slide-in-from-top-2 text-popover-foreground data-[state=closed]:animate-out data-[state=open]:animate-in outline-none",
      className,
    )}
    {...props}
  >
    <div className="border-muted mt-4 space-y-2 border-l-2 pl-4">
      {children}
    </div>
  </CollapsibleContent>
);
