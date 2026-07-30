import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "@rstest/core";

import { accumulateUsage, selectHeaderTokenUsage } from "@/core/messages/usage";
import {
  getAssistantTurnUsageMessages,
  getMessageGroups,
} from "@/core/messages/utils";

/**
 * 覆盖“accumulates each AI message usage only once by message id”这一可观察行为，防止相关边界在重构后回归。

 */

test("accumulates each AI message usage only once by message id", () => {
  const aiMessage = {
    id: "ai-1",
    type: "ai",
    content: "Answer",
    usage_metadata: { input_tokens: 10, output_tokens: 5, total_tokens: 15 },
  } as Message;

  expect(accumulateUsage([aiMessage, aiMessage])).toEqual({
    inputTokens: 10,
    outputTokens: 5,
    totalTokens: 15,
  });
});

/**
 * 覆盖“counts later usage-bearing snapshots for the same AI message id”这一可观察行为，防止相关边界在重构后回归。

 */

test("counts later usage-bearing snapshots for the same AI message id", () => {
  const earlySnapshot = {
    id: "ai-1",
    type: "ai",
    content: "Streaming...",
  } as Message;
  const completedSnapshot = {
    id: "ai-1",
    type: "ai",
    content: "Complete answer",
    usage_metadata: { input_tokens: 10, output_tokens: 5, total_tokens: 15 },
  } as Message;

  expect(accumulateUsage([earlySnapshot, completedSnapshot])).toEqual({
    inputTokens: 10,
    outputTokens: 5,
    totalTokens: 15,
  });
});

/**
 * 覆盖“reads usage metadata from additional kwargs when the SDK nests it there”这一可观察行为，防止相关边界在重构后回归。

 */

test("reads usage metadata from additional kwargs when the SDK nests it there", () => {
  const aiMessage = {
    id: "ai-1",
    type: "ai",
    content: "Answer",
    additional_kwargs: {
      usage_metadata: {
        input_tokens: 8,
        output_tokens: 3,
        total_tokens: 11,
      },
    },
  } as unknown as Message;

  expect(accumulateUsage([aiMessage])).toEqual({
    inputTokens: 8,
    outputTokens: 3,
    totalTokens: 11,
  });
});

/**
 * 覆盖“keeps header and per-turn aggregation consistent for a reasoning+answer message”这一可观察行为，防止相关边界在重构后回归。

 */

test("keeps header and per-turn aggregation consistent for a reasoning+answer message", () => {
  // 一条同时携带推理（此处通过内联 <think>）和回答文本的 AI 消息现在恰好落入一个
  // 助手分组（#3868），因此它在每回合聚合和页头总量中均只计数一次。按 ID 去重（见
  // “accumulates each AI message usage only once”）仍是深度防御措施，以防未来某种
  // 分组方式重新引入重复项。
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Explain this",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "<think>checking context</think>Final answer",
      usage_metadata: { input_tokens: 20, output_tokens: 7, total_tokens: 27 },
    },
  ] as Message[];

  const groups = getMessageGroups(messages);
  const usageMessagesByGroupIndex = getAssistantTurnUsageMessages(groups);
  const turnUsageMessages = usageMessagesByGroupIndex.at(-1);

  expect(groups.map((group) => group.type)).toEqual(["human", "assistant"]);
  expect(turnUsageMessages?.map((message) => message.id)).toEqual(["ai-1"]);
  expect(accumulateUsage(messages)).toEqual(
    accumulateUsage(turnUsageMessages!),
  );
  expect(accumulateUsage(turnUsageMessages!)).toEqual({
    inputTokens: 20,
    outputTokens: 7,
    totalTokens: 27,
  });
});

/**
 * 覆盖“prefers backend thread usage for header totals”这一可观察行为，防止相关边界在重构后回归。

 */

test("prefers backend thread usage for header totals", () => {
  const messages = [
    {
      id: "ai-visible",
      type: "ai",
      content: "Visible answer",
      usage_metadata: { input_tokens: 10, output_tokens: 5, total_tokens: 15 },
    },
  ] as Message[];

  expect(
    selectHeaderTokenUsage({
      backendUsage: { inputTokens: 100, outputTokens: 50, totalTokens: 150 },
      messages,
    }),
  ).toEqual({
    inputTokens: 100,
    outputTokens: 50,
    totalTokens: 150,
  });
});

/**
 * 覆盖“adds current in-flight message usage to backend header totals”这一可观察行为，防止相关边界在重构后回归。

 */

test("adds current in-flight message usage to backend header totals", () => {
  const completedMessages = [
    {
      id: "ai-completed",
      type: "ai",
      content: "Completed answer",
      usage_metadata: { input_tokens: 10, output_tokens: 5, total_tokens: 15 },
    },
    {
      id: "ai-pending",
      type: "ai",
      content: "Streaming answer",
      usage_metadata: { input_tokens: 4, output_tokens: 6, total_tokens: 10 },
    },
  ] as Message[];

  expect(
    selectHeaderTokenUsage({
      backendUsage: { inputTokens: 100, outputTokens: 50, totalTokens: 150 },
      messages: completedMessages,
      pendingMessages: [completedMessages[1]!],
    }),
  ).toEqual({
    inputTokens: 104,
    outputTokens: 56,
    totalTokens: 160,
  });
});

/**
 * 覆盖“falls back to visible messages when backend usage is unavailable or zero”这一可观察行为，防止相关边界在重构后回归。

 */

test("falls back to visible messages when backend usage is unavailable or zero", () => {
  const messages = [
    {
      id: "ai-visible",
      type: "ai",
      content: "Visible answer",
      usage_metadata: { input_tokens: 10, output_tokens: 5, total_tokens: 15 },
    },
  ] as Message[];

  expect(
    selectHeaderTokenUsage({
      backendUsage: null,
      messages,
    }),
  ).toEqual({
    inputTokens: 10,
    outputTokens: 5,
    totalTokens: 15,
  });
  expect(
    selectHeaderTokenUsage({
      backendUsage: { inputTokens: 0, outputTokens: 0, totalTokens: 0 },
      messages,
    }),
  ).toEqual({
    inputTokens: 10,
    outputTokens: 5,
    totalTokens: 15,
  });
});
