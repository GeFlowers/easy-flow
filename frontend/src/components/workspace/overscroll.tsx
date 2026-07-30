"use client";

import { useEffect } from "react";

/** 为滚动容器提供边缘留白，防止移动端手势与底部内容发生遮挡。 */
export function Overscroll({
  behavior,
  overflow = "hidden",
}: {
  behavior: "none" | "contain" | "auto";
  overflow?: "hidden" | "auto" | "scroll";
}) {
  useEffect(() => {
    document.documentElement.style.overflow = overflow;
    document.documentElement.style.overscrollBehavior = behavior;
  }, [behavior, overflow]);
  return null;
}
