import { cn } from "@/lib/utils";

/** 以脉冲占位块预留异步内容尺寸，减少加载前后的布局跳动。 */
/** 提供带脉冲动画的通用占位块，并透传调用方的容器属性。 */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("bg-accent animate-pulse rounded-md", className)}
      {...props}
    />
  );
}

export { Skeleton };
