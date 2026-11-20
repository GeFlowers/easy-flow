import * as React from "react";

/** 提供带边框、背景和纵向间距的通用卡片外框。 */
function Card({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card"
      className={[
        "bg-card text-card-foreground flex flex-col gap-6 rounded-xl border py-6 shadow-sm",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      {...props}
    />
  );
}

/** 排列卡片标题区，并在存在操作按钮时预留独立网格列。 */
function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={[
        "@container/card-header grid auto-rows-min grid-rows-[auto_auto] items-start gap-2 px-6 has-data-[slot=card-action]:grid-cols-[1fr_auto] [.border-b]:pb-6",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      {...props}
    />
  );
}

/** 用较粗字重显示卡片标题。 */
function CardTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-title"
      className={["leading-none font-semibold", className]
        .filter(Boolean)
        .join(" ")}
      {...props}
    />
  );
}

/** 展示卡片标题下方的低强调度说明。 */
function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-description"
      className={["text-muted-foreground text-sm", className]
        .filter(Boolean)
        .join(" ")}
      {...props}
    />
  );
}

/** 将卡片操作定位在标题区网格的右上角。 */
function CardAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-action"
      className={[
        "col-start-2 row-span-2 row-start-1 self-start justify-self-end",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      {...props}
    />
  );
}

/** 为卡片主体内容提供与标题区一致的水平内边距。 */
function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-content"
      className={["px-6", className].filter(Boolean).join(" ")}
      {...props}
    />
  );
}

/** 对齐卡片底部操作，并在上边框存在时增加分隔间距。 */
function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={["flex items-center px-6 [.border-t]:pt-6", className]
        .filter(Boolean)
        .join(" ")}
      {...props}
    />
  );
}

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
};
