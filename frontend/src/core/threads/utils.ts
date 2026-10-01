import type { Message } from "@langchain/langgraph-sdk";

import type { AgentThread, AgentThreadContext } from "./types";

/** 线程来源渠道的展示信息。 */
export type ChannelThreadSource = {
  type: "im_channel";
  provider: string;
  label: string;
};

type ThreadRouteTarget =
  | string
  | {
      thread_id: string;
      context?: Pick<AgentThreadContext, "agent_name"> | null;
      metadata?: Record<string, unknown> | null;
    };

/** 构建线程在当前语言与代理上下文中的页面路径。 */
export function pathOfThread(
  thread: ThreadRouteTarget,
  context?: Pick<AgentThreadContext, "agent_name"> | null,
) {
  const threadId = typeof thread === "string" ? thread : thread.thread_id;
  let agentName: string | undefined;
  if (typeof thread === "string") {
    agentName = context?.agent_name;
  } else {
    agentName = thread.context?.agent_name;
    if (!agentName) {
      const metaAgent = thread.metadata?.agent_name;
      if (typeof metaAgent === "string") {
        agentName = metaAgent;
      }
    }
  }

  return agentName
    ? `/workspace/agents/${encodeURIComponent(agentName)}/chats/${threadId}`
    : `/workspace/chats/${threadId}`;
}

/** 提取消息内容中的紧凑纯文本。 */
export function textOfMessage(message: Message) {
  if (typeof message.content === "string") {
    return message.content;
  } else if (Array.isArray(message.content)) {
    // 单行使用方（输入框、标题）采用无分隔拼接；正文渲染则由
    // extractContentFromMessage 使用换行连接多段内容。
    const text = message.content
      .map((part) =>
        typeof part === "string" ? part : part.type === "text" ? part.text : "",
      )
      .join("");
    return text.length > 0 ? text : null;
  }
  return null;
}

/** 获取线程标题，缺失时返回本地化的默认标题。 */
export function titleOfThread(thread: AgentThread) {
  return thread.values?.title ?? "Untitled";
}

const CHANNEL_PROVIDER_LABELS: Record<string, string> = {
  wechat: "WeChat",
  wecom: "WeCom",
};

/** 将渠道提供方标识转换为标题中的显示名称。 */
function labelOfChannelProvider(provider: string) {
  return CHANNEL_PROVIDER_LABELS[provider] ?? provider;
}

/** 提取线程来源渠道的显示信息。 */
export function channelSourceOfThread(
  thread: Pick<AgentThread, "metadata">,
): ChannelThreadSource | null {
  const source = thread.metadata?.channel_source;
  if (!source || typeof source !== "object" || Array.isArray(source)) {
    return null;
  }

  if (Reflect.get(source, "type") !== "im_channel") {
    return null;
  }

  const provider = Reflect.get(source, "provider");
  if (typeof provider !== "string" || provider.trim().length === 0) {
    return null;
  }

  const normalizedProvider = provider.trim().toLowerCase();
  return {
    type: "im_channel",
    provider: normalizedProvider,
    label: labelOfChannelProvider(normalizedProvider),
  };
}
