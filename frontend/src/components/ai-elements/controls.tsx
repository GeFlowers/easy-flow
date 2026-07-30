"use client";

import { cn } from "@/lib/utils";
import { Controls as ControlsPrimitive } from "@xyflow/react";
import type { ComponentProps } from "react";

/** ControlsProps 的公开类型定义。 */
export type ControlsProps = ComponentProps<typeof ControlsPrimitive>;

/** Controls 组件：提供对应的界面结构与交互语义。 */
export const Controls = ({ className, ...props }: ControlsProps) => (
  <ControlsPrimitive
    className={cn(
      "bg-card gap-px overflow-hidden rounded-md border p-1 shadow-none!",
      "[&>button]:hover:bg-secondary! [&>button]:rounded-md [&>button]:border-none! [&>button]:bg-transparent!",
      className,
    )}
    {...props}
  />
);
