import { ChatProviders } from "./providers";

/** 为普通会话页面提供共享的流式输入、制品与子任务上下文。 */
export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <ChatProviders>{children}</ChatProviders>;
}
