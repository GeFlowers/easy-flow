import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, test } from "@rstest/core";

import {
  extractContentFromMessage,
  extractTextFromMessage,
  extractReasoningContentFromMessage,
  getBranchableAssistantGroupIds,
  getMessageCopyData,
  getAssistantTurnCopyData,
  getAssistantTurnUsageMessages,
  getMessageGroups,
  getStreamingMessageLookup,
  hasContent,
  hasReasoning,
  isAssistantMessageGroupStreaming,
  stripUploadedFilesTag,
} from "@/core/messages/utils";

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 aiMessage 的约定。

 */

function aiMessage(content: string): Message {
  return {
    id: "ai-1",
    type: "ai",
    content,
  } as Message;
}

/**
 * 覆盖“aggregates token usage messages once per assistant turn”这一可观察行为，防止相关边界在重构后回归。

 */

test("aggregates token usage messages once per assistant turn", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Plan a trip",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "",
      tool_calls: [{ id: "tool-1", name: "web_search", args: {} }],
      usage_metadata: { input_tokens: 10, output_tokens: 5, total_tokens: 15 },
    },
    {
      id: "tool-1-result",
      type: "tool",
      name: "web_search",
      tool_call_id: "tool-1",
      content: "[]",
    },
    {
      id: "ai-2",
      type: "ai",
      content: "Here is the itinerary",
      usage_metadata: { input_tokens: 2, output_tokens: 8, total_tokens: 10 },
    },
    {
      id: "human-2",
      type: "human",
      content: "Make it shorter",
    },
    {
      id: "ai-3",
      type: "ai",
      content: "Short version",
      usage_metadata: { input_tokens: 1, output_tokens: 1, total_tokens: 2 },
    },
  ] as Message[];

  const groups = getMessageGroups(messages);
  const usageMessagesByGroupIndex = getAssistantTurnUsageMessages(groups);

  expect(groups.map((group) => group.type)).toEqual([
    "human",
    "assistant:processing",
    "assistant",
    "human",
    "assistant",
  ]);

  expect(
    usageMessagesByGroupIndex.map(
      (groupMessages) => groupMessages?.map((message) => message.id) ?? null,
    ),
  ).toEqual([null, null, ["ai-1", "ai-2"], null, ["ai-3"]]);
});

describe("branchable assistant groups", () => {
  const messages = [
    { id: "human-1", type: "human", content: "First question" },
    { id: "ai-history", type: "ai", content: "Historical final answer" },
    { id: "human-2", type: "human", content: "Complex question" },
    { id: "ai-intermediate", type: "ai", content: "Intermediate answer" },
    {
      id: "ai-tool",
      type: "ai",
      content: "",
      tool_calls: [{ id: "tool-1", name: "write_todos", args: {} }],
    },
    {
      id: "tool-result",
      type: "tool",
      name: "write_todos",
      tool_call_id: "tool-1",
      content: "Todos updated",
    },
    { id: "ai-final", type: "ai", content: "Final answer" },
  ] as Message[];

  /**
   * 覆盖“keeps historical turns branchable and selects only the final AI group in the current completed turn”这一可观察行为，防止相关边界在重构后回归。

   */

  test("keeps historical turns branchable and selects only the final AI group in the current completed turn", () => {
    const groups = getMessageGroups(messages);

    expect([...getBranchableAssistantGroupIds(groups, false)]).toEqual([
      "ai-history",
      "ai-final",
    ]);
  });

  /**
   * 覆盖“does not expose the current turn while it is still loading”这一可观察行为，防止相关边界在重构后回归。

   */

  test("does not expose the current turn while it is still loading", () => {
    const groups = getMessageGroups(messages);

    expect([...getBranchableAssistantGroupIds(groups, true)]).toEqual([
      "ai-history",
    ]);
  });

  /**
   * 覆盖“does not expose a completed turn that ends in processing”这一可观察行为，防止相关边界在重构后回归。

   */

  test("does not expose a completed turn that ends in processing", () => {
    const groups = getMessageGroups(messages.slice(0, -1));

    expect([...getBranchableAssistantGroupIds(groups, false)]).toEqual([
      "ai-history",
    ]);
  });
});

/**
 * 覆盖“reasoning + content (no tool calls) yields a single assistant bubble, not a duplicate processing group”这一可观察行为，防止相关边界在重构后回归。

 */

test("reasoning + content (no tool calls) yields a single assistant bubble, not a duplicate processing group", () => {
  // #3868 的回归场景：在 thinking/pro/ultra 模式中，最终助手消息同时携带
  // reasoning_content 和回答文本。其推理必须只展示一次——在助手气泡的
  // <Reasoning> 可折叠区内。若也将同一消息放入处理组，气泡上方的
  // ChainOfThought 面板会再次绘制完全相同的推理。
  const messages = [
    { id: "human-1", type: "human", content: "Why is the sky blue?" },
    {
      id: "ai-1",
      type: "ai",
      content: "Rayleigh scattering makes the sky blue.",
      additional_kwargs: { reasoning_content: "Recall Rayleigh scattering." },
    },
  ] as Message[];

  const groups = getMessageGroups(messages);

  expect(groups.map((group) => group.type)).toEqual(["human", "assistant"]);

  // 携带推理的消息恰好落入一个分组，因此回合用量聚合绝不会重复计数（见 #2770）。
  const turnUsage = getAssistantTurnUsageMessages(groups);
  expect(turnUsage.at(-1)?.map((message) => message.id)).toEqual(["ai-1"]);
});

/**
 * 覆盖“keeps tool-call reasoning in the processing group while the final answer's reasoning rides its own bubble”这一可观察行为，防止相关边界在重构后回归。

 */

test("keeps tool-call reasoning in the processing group while the final answer's reasoning rides its own bubble", () => {
  // #3868 的配套场景：只有同时成为助手气泡的消息（含内容、无工具调用）会被从
  // 处理组中取出。附加在中间工具调用步骤上的推理仍应与其工具步骤一起留在上方。
  const messages = [
    { id: "human-1", type: "human", content: "Search and summarize" },
    {
      id: "ai-1",
      type: "ai",
      content: "",
      additional_kwargs: { reasoning_content: "I should search first." },
      tool_calls: [{ id: "tool-1", name: "web_search", args: { query: "x" } }],
    },
    {
      id: "tool-1-result",
      type: "tool",
      name: "web_search",
      tool_call_id: "tool-1",
      content: "[]",
    },
    {
      id: "ai-2",
      type: "ai",
      content: "Here is the summary.",
      additional_kwargs: { reasoning_content: "Synthesize the findings." },
    },
  ] as Message[];

  const groups = getMessageGroups(messages);

  expect(groups.map((group) => group.type)).toEqual([
    "human",
    "assistant:processing",
    "assistant",
  ]);
  expect(groups[1]?.messages.map((message) => message.id)).toEqual([
    "ai-1",
    "tool-1-result",
  ]);
  expect(groups[2]?.messages.map((message) => message.id)).toEqual(["ai-2"]);
});

describe("inline <think> tag splitting", () => {
  /**
   * 覆盖“strips a fully closed <think> block from AI content”这一可观察行为，防止相关边界在重构后回归。
   */
  test("strips a fully closed <think> block from AI content", () => {
    const message = aiMessage("<think>internal reasoning</think>final answer");
    expect(extractContentFromMessage(message)).toBe("final answer");
    expect(extractReasoningContentFromMessage(message)).toBe(
      "internal reasoning",
    );
  });

  /**
   * 覆盖“strips multiple closed <think> blocks and joins their reasoning”这一可观察行为，防止相关边界在重构后回归。

   */

  test("strips multiple closed <think> blocks and joins their reasoning", () => {
    const message = aiMessage(
      "<think>step one</think>between<think>step two</think>after",
    );
    expect(extractContentFromMessage(message)).toBe("betweenafter");
    expect(extractReasoningContentFromMessage(message)).toBe(
      "step one\n\nstep two",
    );
  });

  /**
   * 覆盖“during streaming, an unclosed <think> tag does not leak its tail into content”这一可观察行为，防止相关边界在重构后回归。

   */

  test("during streaming, an unclosed <think> tag does not leak its tail into content", () => {
    // 模拟流式传输中已累积内容、但 </think> 尚未到达的时刻。
    const message = aiMessage(
      "<think>I need to analyze the user's question step by",
    );
    expect(extractContentFromMessage(message)).toBe("");
    expect(extractContentFromMessage(message)).not.toContain("<think>");
    expect(extractReasoningContentFromMessage(message)).toBe(
      "I need to analyze the user's question step by",
    );
  });

  /**
   * 覆盖“preamble before an unclosed <think> stays in content”这一可观察行为，防止相关边界在重构后回归。

   */

  test("preamble before an unclosed <think> stays in content", () => {
    const message = aiMessage(
      "Here is part of the answer.<think>but wait, let me reconsider",
    );
    expect(extractContentFromMessage(message)).toBe(
      "Here is part of the answer.",
    );
    expect(extractReasoningContentFromMessage(message)).toBe(
      "but wait, let me reconsider",
    );
  });

  /**
   * 覆盖“closed <think> followed by a trailing unclosed <think> merges both into reasoning”这一可观察行为，防止相关边界在重构后回归。

   */

  test("closed <think> followed by a trailing unclosed <think> merges both into reasoning", () => {
    const message = aiMessage(
      "<think>first step</think>partial answer<think>second step still streaming",
    );
    expect(extractContentFromMessage(message)).toBe("partial answer");
    expect(extractReasoningContentFromMessage(message)).toBe(
      "first step\n\nsecond step still streaming",
    );
  });

  /**
   * 覆盖“hasReasoning recognises an unclosed <think> tag mid-stream”这一可观察行为，防止相关边界在重构后回归。

   */

  test("hasReasoning recognises an unclosed <think> tag mid-stream", () => {
    expect(hasReasoning(aiMessage("<think>thinking in progress"))).toBe(true);
  });

  /**
   * 覆盖“hasContent excludes an unclosed <think> tail when no preamble exists”这一可观察行为，防止相关边界在重构后回归。

   */

  test("hasContent excludes an unclosed <think> tail when no preamble exists", () => {
    expect(hasContent(aiMessage("<think>thinking in progress"))).toBe(false);
  });

  /**
   * 覆盖“hasContent stays true when preamble precedes an unclosed <think>”这一可观察行为，防止相关边界在重构后回归。

   */

  test("hasContent stays true when preamble precedes an unclosed <think>", () => {
    expect(hasContent(aiMessage("preamble<think>still thinking"))).toBe(true);
  });

  /**
   * 覆盖“a lone <think> open tag with no body yields no reasoning and no content”这一可观察行为，防止相关边界在重构后回归。

   */

  test("a lone <think> open tag with no body yields no reasoning and no content", () => {
    const message = aiMessage("<think>");
    expect(extractContentFromMessage(message)).toBe("");
    expect(extractReasoningContentFromMessage(message)).toBeNull();
    expect(hasReasoning(message)).toBe(false);
  });

  /**
   * 覆盖“a literal <think> inside markdown inline code is not treated as reasoning”这一可观察行为，防止相关边界在重构后回归。

   */

  test("a literal <think> inside markdown inline code is not treated as reasoning", () => {
    const message = aiMessage(
      "Use `<think>` markers to delimit reasoning sections.",
    );
    expect(extractContentFromMessage(message)).toBe(
      "Use `<think>` markers to delimit reasoning sections.",
    );
    expect(extractReasoningContentFromMessage(message)).toBeNull();
    expect(hasReasoning(message)).toBe(false);
  });

  /**
   * 覆盖“a backtick-prefixed <think> mid-stream is not split into reasoning”这一可观察行为，防止相关边界在重构后回归。

   */

  test("a backtick-prefixed <think> mid-stream is not split into reasoning", () => {
    // 模拟模型已为字面文档引用输出起始反引号和 `<think>`、但结束反引号尚未到达的
    // 时刻。修复前的行为会在此处永久截断内容。
    const message = aiMessage("Documentation: `<think>");
    expect(extractContentFromMessage(message)).toBe("Documentation: `<think>");
    expect(extractReasoningContentFromMessage(message)).toBeNull();
  });
});

describe("human message internal context stripping", () => {
  /**
   * 覆盖“strips uploaded file context from copy data”这一可观察行为，防止相关边界在重构后回归。
   */
  test("strips uploaded file context from copy data", () => {
    const message = {
      id: "human-with-upload",
      type: "human",
      content:
        "<uploaded_files>\nThe following files were uploaded in this message:\n\n- paper.pdf (1.0 MB)\n  Path: /mnt/user-data/uploads/paper.pdf\n</uploaded_files>\n\nSummarize this paper",
    } as Message;

    expect(getMessageCopyData(message)).toBe("Summarize this paper");
  });

  /**
   * 覆盖“strips slash skill activation context from display content”这一可观察行为，防止相关边界在重构后回归。

   */

  test("strips slash skill activation context from display content", () => {
    const content =
      "<slash_skill_activation>\n<skill_content># Secret SKILL.md</skill_content>\n</slash_skill_activation>\nreal user task";

    expect(stripUploadedFilesTag(content)).toBe("real user task");
  });

  /**
   * 覆盖“hides leaked slash skill activation messages with no user text”这一可观察行为，防止相关边界在重构后回归。

   */

  test("hides leaked slash skill activation messages with no user text", () => {
    const messages = [
      {
        id: "slash-activation",
        type: "human",
        content:
          "<slash_skill_activation>\n<skill_content># Secret SKILL.md</skill_content>\n</slash_skill_activation>",
      },
      {
        id: "ai-1",
        type: "ai",
        content: "Public answer",
      },
    ] as Message[];

    const groups = getMessageGroups(messages);

    expect(groups.map((group) => group.type)).toEqual(["assistant"]);
    expect(
      groups.flatMap((group) => group.messages).map((message) => message.id),
    ).toEqual(["ai-1"]);
  });
});

/**
 * 覆盖“hides internal todo reminder messages from message groups”这一可观察行为，防止相关边界在重构后回归。

 */

test("hides internal todo reminder messages from message groups", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Audit the middleware",
    },
    {
      id: "todo-reminder-1",
      type: "human",
      name: "todo_completion_reminder",
      content: "<system_reminder>finish todos</system_reminder>",
    },
    {
      id: "todo-reminder-2",
      type: "human",
      name: "todo_reminder",
      content: "<system_reminder>remember todos</system_reminder>",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Done",
    },
  ] as Message[];

  const groups = getMessageGroups(messages);

  expect(groups.map((group) => group.type)).toEqual(["human", "assistant"]);
  expect(
    groups.flatMap((group) => group.messages).map((message) => message.id),
  ).toEqual(["human-1", "ai-1"]);
});

/**
 * 覆盖“hides assistant copy data while that turn is streaming”这一可观察行为，防止相关边界在重构后回归。

 */

test("hides assistant copy data while that turn is streaming", () => {
  const messages = [
    {
      id: "ai-1",
      type: "ai",
      content: "Partial answer",
    },
  ] as Message[];

  expect(getAssistantTurnCopyData(messages)).toBe("Partial answer");
  expect(getAssistantTurnCopyData(messages, { isStreaming: true })).toBeNull();
});

/**
 * 覆盖“marks the latest assistant message as streaming”这一可观察行为，防止相关边界在重构后回归。

 */

test("marks the latest assistant message as streaming", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Still generating",
    },
  ] as Message[];
  const groups = getMessageGroups(messages);
  const assistantGroupIndex = groups.findIndex(
    (group) => group.type === "assistant",
  );

  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndex]?.messages ?? [],
      getStreamingMessageLookup(messages, true, () => ({
        streamMetadata: { langgraph_node: "agent" },
      })),
    ),
  ).toBe(true);
  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndex]?.messages ?? [],
      getStreamingMessageLookup(messages, false, () => ({
        streamMetadata: { langgraph_node: "agent" },
      })),
    ),
  ).toBe(false);
});

/**
 * 覆盖“keeps previous assistant copyable while waiting for a new visible answer”这一可观察行为，防止相关边界在重构后回归。

 */

test("keeps previous assistant copyable while waiting for a new visible answer", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Completed answer",
    },
    {
      id: "opt-human-1",
      type: "human",
      content: "Continue",
    },
  ] as Message[];
  const groups = getMessageGroups(messages);
  const assistantGroupIndex = groups.findIndex(
    (group) => group.type === "assistant",
  );

  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndex]?.messages ?? [],
      getStreamingMessageLookup(messages, true),
    ),
  ).toBe(false);
});

/**
 * 覆盖“keeps previous assistant copyable while a hidden send is starting”这一可观察行为，防止相关边界在重构后回归。

 */

test("keeps previous assistant copyable while a hidden send is starting", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Completed answer",
    },
  ] as Message[];
  const groups = getMessageGroups(messages);
  const assistantGroupIndex = groups.findIndex(
    (group) => group.type === "assistant",
  );

  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndex]?.messages ?? [],
      getStreamingMessageLookup(messages, true),
    ),
  ).toBe(false);
});

/**
 * 覆盖“keeps previous assistant copyable after a hidden send is appended”这一可观察行为，防止相关边界在重构后回归。

 */

test("keeps previous assistant copyable after a hidden send is appended", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Completed answer",
    },
    {
      id: "human-hidden",
      type: "human",
      content: "Save this agent",
      additional_kwargs: { hide_from_ui: true },
    },
  ] as Message[];
  const groups = getMessageGroups(messages);
  const assistantGroupIndex = groups.findIndex(
    (group) => group.type === "assistant",
  );

  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndex]?.messages ?? [],
      getStreamingMessageLookup(messages, true),
    ),
  ).toBe(false);
});

/**
 * 覆盖“uses stream metadata to identify an assistant before optimistic input”这一可观察行为，防止相关边界在重构后回归。

 */

test("uses stream metadata to identify an assistant before optimistic input", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Completed answer",
    },
    {
      id: "ai-2",
      type: "ai",
      content: "Still generating",
    },
    {
      id: "opt-human-1",
      type: "human",
      content: "Continue",
    },
  ] as Message[];
  const assistantGroups = getMessageGroups(messages).filter(
    (group) => group.type === "assistant",
  );
  const groups = getMessageGroups(messages);
  const assistantGroupIndexes = groups
    .map((group, index) => (group.type === "assistant" ? index : -1))
    .filter((index) => index >= 0);

  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndexes[0] ?? -1]?.messages ?? [],
      getStreamingMessageLookup(messages, true, (message) =>
        message.id === "ai-2"
          ? { streamMetadata: { langgraph_node: "agent" } }
          : undefined,
      ),
    ),
  ).toBe(false);
  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndexes[1] ?? -1]?.messages ?? [],
      getStreamingMessageLookup(messages, true, (message) =>
        message.id === "ai-2"
          ? { streamMetadata: { langgraph_node: "agent" } }
          : undefined,
      ),
    ),
  ).toBe(true);
  expect(assistantGroups.map((group) => group.id)).toEqual(["ai-1", "ai-2"]);
});

/**
 * 覆盖“does not mark a completed assistant group streaming from a later processing group”这一可观察行为，防止相关边界在重构后回归。

 */

test("does not mark a completed assistant group streaming from a later processing group", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Visible answer",
    },
    {
      id: "ai-2",
      type: "ai",
      content: "",
      tool_calls: [{ id: "tool-1", name: "web_search", args: {} }],
    },
  ] as Message[];
  const groups = getMessageGroups(messages);
  const assistantGroupIndex = groups.findIndex(
    (group) => group.type === "assistant",
  );

  expect(groups.map((group) => group.type)).toEqual([
    "human",
    "assistant",
    "assistant:processing",
  ]);
  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndex]?.messages ?? [],
      getStreamingMessageLookup(messages, true, (message) =>
        message.id === "ai-2"
          ? { streamMetadata: { langgraph_node: "agent" } }
          : undefined,
      ),
    ),
  ).toBe(false);
});

/**
 * 覆盖“keeps streaming assistant hidden when a hidden control message follows it”这一可观察行为，防止相关边界在重构后回归。

 */

test("keeps streaming assistant hidden when a hidden control message follows it", () => {
  const messages = [
    {
      id: "human-1",
      type: "human",
      content: "Hello",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Still generating",
    },
    {
      id: "human-hidden",
      type: "human",
      content: "Save this agent",
      additional_kwargs: { hide_from_ui: true },
    },
  ] as Message[];
  const groups = getMessageGroups(messages);
  const assistantGroupIndex = groups.findIndex(
    (group) => group.type === "assistant",
  );

  expect(
    isAssistantMessageGroupStreaming(
      groups[assistantGroupIndex]?.messages ?? [],
      getStreamingMessageLookup(messages, true, (message) =>
        message.id === "ai-1"
          ? { streamMetadata: { langgraph_node: "agent" } }
          : undefined,
      ),
    ),
  ).toBe(true);
});

describe("multi-part content with bare-string continuations", () => {
  // Gemini 将首个内容块以携带 thinking signature 的 {type:"text"} 对象流式传输，
  // 随后将续接增量作为纯字符串发出。LangChain 的 Python merge_content 会将其保留为
  // 裸字符串元素，因此最终消息内容为 [{type:"text", ...}, "...rest..."]。
  const geminiMessage = {
    id: "ai-1",
    type: "ai",
    content: [
      {
        type: "text",
        text: "First block carrying the signature.",
        extras: { signature: "abc123" },
        index: 0,
      },
      "Continuation streamed as a bare string.",
    ],
  } as unknown as Message;

  /**
   * 覆盖“extractContentFromMessage includes the bare-string parts”这一可观察行为，防止相关边界在重构后回归。

   */

  test("extractContentFromMessage includes the bare-string parts", () => {
    expect(extractContentFromMessage(geminiMessage)).toBe(
      "First block carrying the signature.\nContinuation streamed as a bare string.",
    );
  });

  /**
   * 覆盖“extractTextFromMessage includes the bare-string parts”这一可观察行为，防止相关边界在重构后回归。

   */

  test("extractTextFromMessage includes the bare-string parts", () => {
    expect(extractTextFromMessage(geminiMessage)).toBe(
      "First block carrying the signature.\nContinuation streamed as a bare string.",
    );
  });
});

describe("orphan tool messages", () => {
  // LangGraph 流模式 “messages-tuple” 可能乱序发出工具结果事件，或从子代理状态回放
  // 这些事件（例如 LocalSandboxProvider 下启用 allow_host_bash 的 bash 子代理）。
  // 此时工具消息到达于终止的 assistant/human 分组之后，因此 getMessageGroups 的
  // lastOpenGroup() 会返回 null。
  //
  // 先前行为是 console.error 后丢弃，导致工具结果从 UI 中被静默隐藏。修复后回退为将
  // 孤立工具附加到最近分组，以便用户仍可看到代理执行了什么。

  /**
   * 覆盖“attaches orphan tool message to the most recent group instead of dropping it”这一可观察行为，防止相关边界在重构后回归。

   */

  test("attaches orphan tool message to the most recent group instead of dropping it", () => {
    const messages = [
      { id: "h-1", type: "human", content: "Run something" },
      {
        id: "ai-1",
        type: "ai",
        content: "ok",
        tool_calls: [{ id: "call-1", name: "bash", args: {} }],
      },
      {
        id: "t-1",
        type: "tool",
        name: "bash",
        tool_call_id: "call-1",
        content: "output-1",
      },
      { id: "ai-2", type: "ai", content: "Done." }, // terminal assistant group
      // 孤立工具：到达于终止分组之后，前面没有处理分组。
      {
        id: "t-2",
        type: "tool",
        name: "bash",
        tool_call_id: "call-2",
        content: "output-2",
      },
    ] as Message[];

    const groups = getMessageGroups(messages);

    // 预期分组：human、assistant:processing（ai-1 + t-1）、assistant（ai-2）；
    // t-2 应附加到最后一个分组（assistant），而不是被丢弃。
    const types = groups.map((g) => g.type);
    expect(types).toEqual(["human", "assistant:processing", "assistant"]);

    // 必须能从某个分组获取 t-2——绝不能被静默丢弃。
    const allMessages = groups.flatMap((g) => g.messages);
    const t2 = allMessages.find((m) => m.id === "t-2");
    expect(t2).toBeDefined();
    expect(t2?.type).toBe("tool");
  });

  /**
   * 覆盖“replayed tool with same tool_call_id is not lost (duplicate stream events)”这一可观察行为，防止相关边界在重构后回归。

   */

  test("replayed tool with same tool_call_id is not lost (duplicate stream events)", () => {
    // LangGraph 子代理状态恢复可回放工具结果事件。前端日志显示同一 tool_call_id 到达
    // 两次。两次出现都应在 UI 中可见，而不只是第一次。
    const messages = [
      { id: "h-1", type: "human", content: "q" },
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [{ id: "call-x", name: "bash", args: {} }],
      },
      {
        id: "t-1a",
        type: "tool",
        name: "bash",
        tool_call_id: "call-x",
        content: "first delivery",
      },
      // 终止助手分组结束本回合并关闭处理分组。没有这次交错时，回放的 t-1b 仍会走
      // 未改变的正常路径；有了它，t-1b 到达时 lastOpenGroup() 返回 null，必须走新的
      // 回退分支才可见。
      { id: "ai-2", type: "ai", content: "Done." },
      // 原始 tool_call 的回放工具结果——必须进入新的 else-if (groups.length > 0)
      // 分支，而不是被丢弃。
      {
        id: "t-1b",
        type: "tool",
        name: "bash",
        tool_call_id: "call-x",
        content: "first delivery",
      },
    ] as Message[];

    const groups = getMessageGroups(messages);
    const allMessages = groups.flatMap((g) => g.messages);

    // 严格断言：必须能从某个分组获取回放的工具消息（即通过新回退逻辑附加）。修复前，
    // 它会在 console.error 后被静默丢弃。
    const t1b = allMessages.find((m) => m.id === "t-1b");
    expect(t1b).toBeDefined();
    expect(t1b?.type).toBe("tool");
  });
});
