"use client";

import {
  Tooltip as TooltipPrimitive,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/** 封装统一的提示层，并保留触发元素的键盘与读屏访问能力。 */
export function Tooltip({
  children,
  content,
  ...props
}: {
  children: React.ReactNode;
  content?: React.ReactNode;
}) {
  return (
    <TooltipPrimitive delayDuration={500} {...props}>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent>{content}</TooltipContent>
    </TooltipPrimitive>
  );
}
