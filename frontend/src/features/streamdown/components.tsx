"use client";

import {
  MessageResponse,
  type MessageResponseProps,
} from "@/components/ai-elements/message";
import {
  ReasoningContent,
  type ReasoningContentProps,
} from "@/components/ai-elements/reasoning";
import {
  ClipboardSafeStreamdown,
  type ClipboardSafeStreamdownProps,
} from "@/components/ai-elements/streamdown";

import {
  useSafeStreamdownChildren,
  useSafeStreamdownMarkdown,
} from "./safe-children";

/** 使用安全预处理结果渲染通用流式内容。 */
export function SafeStreamdown({
  children,
  ...props
}: ClipboardSafeStreamdownProps) {
  const safeChildren = useSafeStreamdownChildren(children);

  return (
    <ClipboardSafeStreamdown {...props}>{safeChildren}</ClipboardSafeStreamdown>
  );
}

/** 使用安全预处理结果渲染消息回复。 */
export function SafeMessageResponse({
  children,
  ...props
}: MessageResponseProps) {
  const safeChildren = useSafeStreamdownChildren(children);

  return <MessageResponse {...props}>{safeChildren}</MessageResponse>;
}

/** 使用安全预处理结果渲染推理内容。 */
export function SafeReasoningContent({
  children,
  ...props
}: ReasoningContentProps) {
  const safeChildren = useSafeStreamdownMarkdown(children);

  return <ReasoningContent {...props}>{safeChildren}</ReasoningContent>;
}
