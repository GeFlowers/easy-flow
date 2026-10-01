"use client";

import type { LucideIcon } from "lucide-react";
import { Children, type ComponentProps } from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

const STAGGER_DELAY_MS = 60;
const STAGGER_DELAY_MS_OFFSET = 250;

export type SuggestionsProps = ComponentProps<typeof ScrollArea>;

/** 将建议选项换行排列，逐项错开淡入，并提供横向滚动容器。 */
export const Suggestions = ({
  className,
  children,
  ...props
}: SuggestionsProps) => (
  <ScrollArea className="overflow-x-auto whitespace-normal" {...props}>
    <div
      className={cn("flex w-full flex-wrap items-center gap-2", className)}
      data-slot="suggestions-list"
    >
      {Children.map(children, (child, index) =>
        child != null ? (
          <span
            className="animate-fade-in-up max-w-full opacity-0"
            style={{
              animationDelay: `${STAGGER_DELAY_MS_OFFSET + index * STAGGER_DELAY_MS}ms`,
            }}
          >
            {child}
          </span>
        ) : (
          child
        ),
      )}
    </div>
    <ScrollBar className="hidden" orientation="horizontal" />
  </ScrollArea>
);

export type SuggestionProps = Omit<ComponentProps<typeof Button>, "onClick"> & {
  suggestion: React.ReactNode;
  icon?: LucideIcon;
  onClick?: () => void;
};

/** 把单条建议呈现为可点击按钮，并可选显示图标及自定义子内容。 */
export const Suggestion = ({
  suggestion,
  onClick,
  className,
  icon: Icon,
  variant = "outline",
  size = "sm",
  children,
  ...props
}: SuggestionProps) => {
  /** 调用可选的建议回调，由父级决定如何填入或提交该建议。 */
  const handleClick = () => {
    onClick?.();
  };

  return (
    <Button
      className={cn(
        "text-muted-foreground dark:bg-background h-auto max-w-full cursor-pointer rounded-full px-4 py-2 text-center text-xs font-normal whitespace-normal",
        className,
      )}
      onClick={handleClick}
      size={size}
      type="button"
      variant={variant}
      {...props}
    >
      {Icon && <Icon className="size-4" />}
      {children ?? suggestion}
    </Button>
  );
};
