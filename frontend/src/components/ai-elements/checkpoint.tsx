"use client";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { BookmarkIcon, type LucideProps } from "lucide-react";
import type { ComponentProps, HTMLAttributes } from "react";

/** CheckpointProps 的公开类型定义。 */
export type CheckpointProps = HTMLAttributes<HTMLDivElement>;

/** Checkpoint 组件：提供对应的界面结构与交互语义。 */
export const Checkpoint = ({
  className,
  children,
  ...props
}: CheckpointProps) => (
  <div
    className={cn(
      "text-muted-foreground flex items-center gap-0.5 overflow-hidden",
      className,
    )}
    {...props}
  >
    {children}
    <Separator />
  </div>
);

/** CheckpointIconProps 的公开类型定义。 */
export type CheckpointIconProps = LucideProps;

/** CheckpointIcon 组件：提供对应的界面结构与交互语义。 */
export const CheckpointIcon = ({
  className,
  children,
  ...props
}: CheckpointIconProps) =>
  children ?? (
    <BookmarkIcon className={cn("size-4 shrink-0", className)} {...props} />
  );

/** CheckpointTriggerProps 的公开类型定义。 */
export type CheckpointTriggerProps = ComponentProps<typeof Button> & {
  tooltip?: string;
};

/** CheckpointTrigger 组件：提供对应的界面结构与交互语义。 */
export const CheckpointTrigger = ({
  children,
  className,
  variant = "ghost",
  size = "sm",
  tooltip,
  ...props
}: CheckpointTriggerProps) =>
  tooltip ? (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button size={size} type="button" variant={variant} {...props}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent align="start" side="bottom">
        {tooltip}
      </TooltipContent>
    </Tooltip>
  ) : (
    <Button size={size} type="button" variant={variant} {...props}>
      {children}
    </Button>
  );
