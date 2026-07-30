import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "@rstest/core";

import {
  channelSourceOfThread,
  pathOfThread,
  textOfMessage,
} from "@/core/threads/utils";

/**
 * 覆盖“uses standard chat route when thread has no agent context”这一可观察行为，防止相关边界在重构后回归。

 */

test("uses standard chat route when thread has no agent context", () => {
  expect(pathOfThread("thread-123")).toBe("/workspace/chats/thread-123");
  expect(
    pathOfThread({
      thread_id: "thread-123",
    }),
  ).toBe("/workspace/chats/thread-123");
});

/**
 * 覆盖“uses agent chat route when thread context has agent_name”这一可观察行为，防止相关边界在重构后回归。

 */

test("uses agent chat route when thread context has agent_name", () => {
  expect(
    pathOfThread({
      thread_id: "thread-123",
      context: { agent_name: "researcher" },
    }),
  ).toBe("/workspace/agents/researcher/chats/thread-123");
});

/**
 * 覆盖“uses provided context when pathOfThread is called with a thread id”这一可观察行为，防止相关边界在重构后回归。

 */

test("uses provided context when pathOfThread is called with a thread id", () => {
  expect(pathOfThread("thread-123", { agent_name: "ops agent" })).toBe(
    "/workspace/agents/ops%20agent/chats/thread-123",
  );
});

/**
 * 覆盖“uses agent chat route when thread metadata has agent_name”这一可观察行为，防止相关边界在重构后回归。

 */

test("uses agent chat route when thread metadata has agent_name", () => {
  expect(
    pathOfThread({
      thread_id: "thread-456",
      metadata: { agent_name: "coder" },
    }),
  ).toBe("/workspace/agents/coder/chats/thread-456");
});

/**
 * 覆盖“prefers context.agent_name over metadata.agent_name”这一可观察行为，防止相关边界在重构后回归。

 */

test("prefers context.agent_name over metadata.agent_name", () => {
  expect(
    pathOfThread({
      thread_id: "thread-789",
      context: { agent_name: "from-context" },
      metadata: { agent_name: "from-metadata" },
    }),
  ).toBe("/workspace/agents/from-context/chats/thread-789");
});

/**
 * 覆盖“reads IM channel source metadata”这一可观察行为，防止相关边界在重构后回归。

 */

test("reads IM channel source metadata", () => {
  expect(
    channelSourceOfThread({
      metadata: {
        channel_source: {
          type: "im_channel",
          provider: "feishu",
          chat_id: "oc_123",
        },
      },
    }),
  ).toEqual({
    type: "im_channel",
    provider: "feishu",
    label: "Feishu",
  });
});

/**
 * 覆盖“ignores threads without valid IM channel source metadata”这一可观察行为，防止相关边界在重构后回归。

 */

test("ignores threads without valid IM channel source metadata", () => {
  expect(channelSourceOfThread({ metadata: {} })).toBeNull();
  expect(
    channelSourceOfThread({
      metadata: { channel_source: { provider: "" } },
    }),
  ).toBeNull();
  expect(
    channelSourceOfThread({
      metadata: {
        channel_source: {
          type: "other",
          provider: "feishu",
        },
      },
    }),
  ).toBeNull();
});

/**
 * 覆盖“textOfMessage concatenates object and bare-string content parts”这一可观察行为，防止相关边界在重构后回归。

 */

test("textOfMessage concatenates object and bare-string content parts", () => {
  // Gemini 的最终形状：第一个带签名的 {type:text} 块加裸字符串续接。
  // textOfMessage 为单行消费者将其平坦拼接（""）。
  const message = {
    id: "ai-1",
    type: "ai",
    content: [
      {
        type: "text",
        text: "First block.",
        extras: { signature: "abc123" },
        index: 0,
      },
      " Continuation as a bare string.",
    ],
  } as unknown as Message;

  expect(textOfMessage(message)).toBe(
    "First block. Continuation as a bare string.",
  );
});

/**
 * 覆盖“textOfMessage returns null when array content has no text”这一可观察行为，防止相关边界在重构后回归。

 */

test("textOfMessage returns null when array content has no text", () => {
  const message = {
    id: "ai-1",
    type: "ai",
    content: [{ type: "image_url", image_url: "https://example.com/x.png" }],
  } as unknown as Message;

  expect(textOfMessage(message)).toBeNull();
});
