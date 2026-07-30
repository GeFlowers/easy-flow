import { cn } from "@/lib/utils";
import { Panel as PanelPrimitive } from "@xyflow/react";
import type { ComponentProps } from "react";

type PanelProps = ComponentProps<typeof PanelPrimitive>;

/** Panel 组件：提供对应的界面结构与交互语义。 */
export const Panel = ({ className, ...props }: PanelProps) => (
  <PanelPrimitive
    className={cn(
      "bg-card m-4 overflow-hidden rounded-md border p-1",
      className,
    )}
    {...props}
  />
);
