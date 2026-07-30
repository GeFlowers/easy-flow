"use client";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { type LucideIcon, XIcon } from "lucide-react";
import type { ComponentProps, HTMLAttributes } from "react";

/** ArtifactProps 的公开类型定义。 */
export type ArtifactProps = HTMLAttributes<HTMLDivElement>;

/** Artifact 组件：提供对应的界面结构与交互语义。 */
export const Artifact = ({ className, ...props }: ArtifactProps) => (
  <div
    className={cn(
      "bg-background flex flex-col overflow-hidden rounded-lg border shadow-lg",
      className,
    )}
    {...props}
  />
);

/** ArtifactHeaderProps 的公开类型定义。 */
export type ArtifactHeaderProps = HTMLAttributes<HTMLDivElement>;

/** ArtifactHeader 组件：提供对应的界面结构与交互语义。 */
export const ArtifactHeader = ({
  className,
  ...props
}: ArtifactHeaderProps) => (
  <div
    className={cn(
      "bg-muted/50 flex items-center justify-between border-b px-4 py-3",
      className,
    )}
    {...props}
  />
);

/** ArtifactCloseProps 的公开类型定义。 */
export type ArtifactCloseProps = ComponentProps<typeof Button>;

/** ArtifactClose 组件：提供对应的界面结构与交互语义。 */
export const ArtifactClose = ({
  className,
  children,
  size = "sm",
  variant = "ghost",
  ...props
}: ArtifactCloseProps) => (
  <Button
    className={cn(
      "text-muted-foreground hover:text-foreground size-8 p-0",
      className,
    )}
    size={size}
    type="button"
    variant={variant}
    {...props}
  >
    {children ?? <XIcon className="size-4" />}
    <span className="sr-only">Close</span>
  </Button>
);

/** ArtifactTitleProps 的公开类型定义。 */
export type ArtifactTitleProps = HTMLAttributes<HTMLParagraphElement>;

/** ArtifactTitle 组件：提供对应的界面结构与交互语义。 */
export const ArtifactTitle = ({ className, ...props }: ArtifactTitleProps) => (
  <div
    className={cn("text-foreground text-sm font-medium", className)}
    {...props}
  />
);

/** ArtifactDescriptionProps 的公开类型定义。 */
export type ArtifactDescriptionProps = HTMLAttributes<HTMLParagraphElement>;

/** ArtifactDescription 组件：提供对应的界面结构与交互语义。 */
export const ArtifactDescription = ({
  className,
  ...props
}: ArtifactDescriptionProps) => (
  <p className={cn("text-muted-foreground text-sm", className)} {...props} />
);

/** ArtifactActionsProps 的公开类型定义。 */
export type ArtifactActionsProps = HTMLAttributes<HTMLDivElement>;

/** ArtifactActions 组件：提供对应的界面结构与交互语义。 */
export const ArtifactActions = ({
  className,
  ...props
}: ArtifactActionsProps) => (
  <div className={cn("flex items-center gap-1", className)} {...props} />
);

/** ArtifactActionProps 的公开类型定义。 */
export type ArtifactActionProps = ComponentProps<typeof Button> & {
  tooltip?: string;
  label?: string;
  icon?: LucideIcon;
};

/** ArtifactAction 组件：提供对应的界面结构与交互语义。 */
export const ArtifactAction = ({
  tooltip,
  label,
  icon: Icon,
  children,
  className,
  size = "sm",
  variant = "ghost",
  ...props
}: ArtifactActionProps) => {
  const button = (
    <Button
      className={cn(
        "text-muted-foreground hover:text-foreground size-8 p-0",
        className,
      )}
      size={size}
      type="button"
      variant={variant}
      {...props}
    >
      {Icon ? <Icon className="size-4" /> : children}
      <span className="sr-only">{label || tooltip}</span>
    </Button>
  );

  if (tooltip) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>{button}</TooltipTrigger>
          <TooltipContent>
            <p>{tooltip}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return button;
};

/** ArtifactContentProps 的公开类型定义。 */
export type ArtifactContentProps = HTMLAttributes<HTMLDivElement>;

/** ArtifactContent 组件：提供对应的界面结构与交互语义。 */
export const ArtifactContent = ({
  className,
  ...props
}: ArtifactContentProps) => (
  <div
    className={cn("min-h-0 flex-1 overflow-auto p-4", className)}
    {...props}
  />
);
