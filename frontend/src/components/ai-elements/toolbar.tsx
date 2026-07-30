import { cn } from "@/lib/utils";
import { NodeToolbar, Position } from "@xyflow/react";
import type { ComponentProps } from "react";

type ToolbarProps = ComponentProps<typeof NodeToolbar>;

/** Toolbar 组件：提供对应的界面结构与交互语义。 */
export const Toolbar = ({ className, ...props }: ToolbarProps) => (
  <NodeToolbar
    className={cn(
      "bg-background flex items-center gap-1 rounded-sm border p-1.5",
      className,
    )}
    position={Position.Bottom}
    {...props}
  />
);
