"use client";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { BookIcon, ChevronDownIcon } from "lucide-react";
import type { ComponentProps } from "react";

/** SourcesProps 的公开类型定义。 */
export type SourcesProps = ComponentProps<"div">;

/** Sources 组件：提供对应的界面结构与交互语义。 */
export const Sources = ({ className, ...props }: SourcesProps) => (
  <Collapsible
    className={cn("not-prose text-primary mb-4 text-xs", className)}
    {...props}
  />
);

/** SourcesTriggerProps 的公开类型定义。 */
export type SourcesTriggerProps = ComponentProps<typeof CollapsibleTrigger> & {
  count: number;
};

/** SourcesTrigger 组件：提供对应的界面结构与交互语义。 */
export const SourcesTrigger = ({
  className,
  count,
  children,
  ...props
}: SourcesTriggerProps) => (
  <CollapsibleTrigger
    className={cn("flex items-center gap-2", className)}
    {...props}
  >
    {children ?? (
      <>
        <p className="font-medium">Used {count} sources</p>
        <ChevronDownIcon className="h-4 w-4" />
      </>
    )}
  </CollapsibleTrigger>
);

/** SourcesContentProps 的公开类型定义。 */
export type SourcesContentProps = ComponentProps<typeof CollapsibleContent>;

/** SourcesContent 组件：提供对应的界面结构与交互语义。 */
export const SourcesContent = ({
  className,
  ...props
}: SourcesContentProps) => (
  <CollapsibleContent
    className={cn(
      "mt-3 flex w-fit flex-col gap-2",
      "data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-top-2 data-[state=open]:slide-in-from-top-2 data-[state=closed]:animate-out data-[state=open]:animate-in outline-none",
      className,
    )}
    {...props}
  />
);

/** SourceProps 的公开类型定义。 */
export type SourceProps = ComponentProps<"a">;

/** Source 组件：提供对应的界面结构与交互语义。 */
export const Source = ({ href, title, children, ...props }: SourceProps) => (
  <a
    className="flex items-center gap-2"
    href={href}
    rel="noopener noreferrer"
    target="_blank"
    {...props}
  >
    {children ?? (
      <>
        <BookIcon className="h-4 w-4" />
        <span className="block font-medium">{title}</span>
      </>
    )}
  </a>
);
