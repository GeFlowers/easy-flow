"use client";

import { Component, type ComponentProps, type ReactNode } from "react";
import { Streamdown } from "streamdown";

import { installClipboardFallback } from "@/core/clipboard";

/** ClipboardSafeStreamdownProps 的公开类型定义。 */
export type ClipboardSafeStreamdownProps = ComponentProps<typeof Streamdown>;

// 仅在客户端修补浏览器全局对象，服务端渲染期间跳过。
if (typeof document !== "undefined") {
  installClipboardFallback();
}

// Streamdown 用于按块拆分内容的 marked 分词器存在相互递归；引用或列表嵌套数千层时会在渲染中
// 造成调用栈溢出，进而影响整个路由。单条消息渲染抛错时，降级为显示该消息的预格式化纯文本。
class StreamdownFallbackBoundary extends Component<
  { raw: ClipboardSafeStreamdownProps["children"]; children: ReactNode },
  { errored: boolean; prevRaw: ClipboardSafeStreamdownProps["children"] }
> {
  state = { errored: false, prevRaw: this.props.raw };

  static getDerivedStateFromError() {
    return { errored: true };
  }

  static getDerivedStateFromProps(
    props: { raw: ClipboardSafeStreamdownProps["children"] },
    state: {
      errored: boolean;
      prevRaw: ClipboardSafeStreamdownProps["children"];
    },
  ) {
    // 内容变化（例如收到下一段流式数据）后重试渲染。
    if (props.raw !== state.prevRaw) {
      return { errored: false, prevRaw: props.raw };
    }
    return null;
  }

  render() {
    if (this.state.errored) {
      return (
        <div className="break-words whitespace-pre-wrap">
          {typeof this.props.raw === "string" ? this.props.raw : null}
        </div>
      );
    }
    return this.props.children;
  }
}

/** ClipboardSafeStreamdown 组件：提供对应的界面结构与交互语义。 */
export function ClipboardSafeStreamdown({
  children,
  ...props
}: ClipboardSafeStreamdownProps) {
  return (
    <StreamdownFallbackBoundary raw={children}>
      <Streamdown {...props}>{children}</Streamdown>
    </StreamdownFallbackBoundary>
  );
}
