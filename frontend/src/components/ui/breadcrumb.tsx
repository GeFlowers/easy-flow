import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { ChevronRight, MoreHorizontal } from "lucide-react";

/** 为面包屑导航提供可访问的导航地标名称。 */
function Breadcrumb({ ...props }: React.ComponentProps<"nav">) {
  return <nav aria-label="breadcrumb" data-slot="breadcrumb" {...props} />;
}

/** 横向排列路径片段。 */
function BreadcrumbList({ className, ...props }: React.ComponentProps<"ol">) {
  return (
    <ol
      data-slot="breadcrumb-list"
      className={[
        "text-muted-foreground flex flex-wrap items-center gap-2.5 text-sm break-words",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      {...props}
    />
  );
}

/** 将单个路径链接或当前页面名称与相邻分隔符对齐。 */
function BreadcrumbItem({ className, ...props }: React.ComponentProps<"li">) {
  return (
    <li
      data-slot="breadcrumb-item"
      className={["inline-flex items-center gap-1.5", className]
        .filter(Boolean)
        .join(" ")}
      {...props}
    />
  );
}

/** 渲染可点击的路径链接；asChild 可把样式和属性转交给子元素。 */
function BreadcrumbLink({
  asChild,
  className,
  ...props
}: React.ComponentProps<"a"> & {
  asChild?: boolean;
}) {
  const Comp = asChild ? Slot : "a";

  return (
    <Comp
      data-slot="breadcrumb-link"
      className={["hover:text-foreground transition-colors", className]
        .filter(Boolean)
        .join(" ")}
      {...props}
    />
  );
}

/** 标记当前路径位置，并通过 aria-current 告知辅助技术其页面状态。 */
function BreadcrumbPage({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="breadcrumb-page"
      role="link"
      aria-disabled="true"
      aria-current="page"
      className={["text-foreground font-normal", className]
        .filter(Boolean)
        .join(" ")}
      {...props}
    />
  );
}

/** 在路径项之间添加装饰性分隔符；默认使用向右箭头。 */
function BreadcrumbSeparator({
  children,
  className,
  ...props
}: React.ComponentProps<"li">) {
  return (
    <li
      data-slot="breadcrumb-separator"
      role="presentation"
      aria-hidden="true"
      className={["[&>svg]:size-3.5", className].filter(Boolean).join(" ")}
      {...props}
    >
      {children ?? <ChevronRight />}
    </li>
  );
}

/** 以省略号表示被折叠的中间路径，且不暴露为可交互内容。 */
function BreadcrumbEllipsis({
  className,
  ...props
}: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="breadcrumb-ellipsis"
      role="presentation"
      aria-hidden="true"
      className={["flex size-9 items-center justify-center", className]
        .filter(Boolean)
        .join(" ")}
      {...props}
    >
      <MoreHorizontal className="size-4" />
      <span className="sr-only">More</span>
    </span>
  );
}

export {
  Breadcrumb,
  BreadcrumbList,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbPage,
  BreadcrumbSeparator,
  BreadcrumbEllipsis,
};
