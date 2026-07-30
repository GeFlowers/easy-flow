import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import {
  formatThreadAsJSON,
  formatThreadAsMarkdown,
} from "@/core/threads/export";
import type { AgentThread } from "@/core/threads/types";

// Bytedance/deer-flow 问题 #3107 BUG-006：聊天导出路径绕过 UI 层隐藏消息过滤器，
// 将推理内容、工具调用及其他“内部”载荷当作用户对话记录的一部分输出。

/**
 * 构造测试所需的稳定夹具，使调用处能够明确复用 makeThread 的约定。

 */

function makeThread(): AgentThread {
  return {
    thread_id: "thread-1",
    created_at: "2026-05-21T00:00:00Z",
    updated_at: "2026-05-21T00:00:00Z",
    metadata: { title: "Demo thread" },
    status: "idle",
    values: { messages: [] },
  } as unknown as AgentThread;
}

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 human 的约定。

 */

function human(content: string, extra: Partial<Message> = {}): Message {
  return {
    id: `h-${content}`,
    type: "human",
    content,
    ...extra,
  } as Message;
}

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 ai 的约定。

 */

function ai(
  content: string,
  extra: Partial<Message> & { tool_calls?: unknown } = {},
): Message {
  return {
    id: `a-${content}`,
    type: "ai",
    content,
    ...extra,
  } as Message;
}

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 toolMsg 的约定。

 */

function toolMsg(content: string): Message {
  return {
    id: `t-${content}`,
    type: "tool",
    content,
    name: "task",
    tool_call_id: "call-1",
  } as unknown as Message;
}

describe("formatThreadAsMarkdown", () => {
  /**
   * 覆盖“includes plain user and assistant text”这一可观察行为，防止相关边界在重构后回归。
   */
  it("includes plain user and assistant text", () => {
    const md = formatThreadAsMarkdown(makeThread(), [
      human("hello"),
      ai("hi there"),
    ]);
    expect(md).toContain("hello");
    expect(md).toContain("hi there");
  });

  /**
   * 覆盖“drops messages marked hide_from_ui”这一可观察行为，防止相关边界在重构后回归。

   */

  it("drops messages marked hide_from_ui", () => {
    const hidden = human("internal system reminder", {
      additional_kwargs: { hide_from_ui: true },
    } as Partial<Message>);
    const md = formatThreadAsMarkdown(makeThread(), [
      hidden,
      ai("public answer"),
    ]);
    expect(md).not.toContain("internal system reminder");
    expect(md).toContain("public answer");
  });

  /**
   * 覆盖“does not emit reasoning_content by default”这一可观察行为，防止相关边界在重构后回归。

   */

  it("does not emit reasoning_content by default", () => {
    const message = ai("final answer", {
      additional_kwargs: {
        reasoning_content: "secret chain of thought",
      },
    } as Partial<Message>);
    const md = formatThreadAsMarkdown(makeThread(), [message]);
    expect(md).not.toContain("secret chain of thought");
    expect(md).not.toContain("Thinking");
  });

  /**
   * 覆盖“does not emit tool calls by default”这一可观察行为，防止相关边界在重构后回归。

   */

  it("does not emit tool calls by default", () => {
    const message = ai("ok", {
      tool_calls: [{ id: "1", name: "task", args: { description: "do work" } }],
    } as Partial<Message>);
    const md = formatThreadAsMarkdown(makeThread(), [message]);
    expect(md).not.toContain("**Tool:**");
    expect(md).not.toContain("`task`");
  });

  /**
   * 覆盖“drops tool result messages”这一可观察行为，防止相关边界在重构后回归。

   */

  it("drops tool result messages", () => {
    const md = formatThreadAsMarkdown(makeThread(), [
      ai("delegating"),
      toolMsg("Task Succeeded. Result: confidential"),
    ]);
    expect(md).not.toContain("confidential");
  });
});

describe("formatThreadAsMarkdown opt-in flags", () => {
  /**
   * 覆盖“emits reasoning when includeReasoning is true”这一可观察行为，防止相关边界在重构后回归。
   */
  it("emits reasoning when includeReasoning is true", () => {
    const message = ai("final answer", {
      additional_kwargs: {
        reasoning_content: "step-by-step chain of thought",
      },
    } as Partial<Message>);
    const md = formatThreadAsMarkdown(makeThread(), [message], {
      includeReasoning: true,
    });
    expect(md).toContain("step-by-step chain of thought");
    expect(md).toContain("Thinking");
  });

  /**
   * 覆盖“emits tool call rows when includeToolCalls is true”这一可观察行为，防止相关边界在重构后回归。

   */

  it("emits tool call rows when includeToolCalls is true", () => {
    const message = ai("ok", {
      tool_calls: [{ id: "1", name: "task", args: { description: "do work" } }],
    } as Partial<Message>);
    const md = formatThreadAsMarkdown(makeThread(), [message], {
      includeToolCalls: true,
    });
    expect(md).toContain("**Tool:**");
    expect(md).toContain("`task`");
  });

  /**
   * 覆盖“keeps hidden messages when includeHidden is true”这一可观察行为，防止相关边界在重构后回归。

   */

  it("keeps hidden messages when includeHidden is true", () => {
    const hidden = human("internal reminder", {
      additional_kwargs: { hide_from_ui: true },
    } as Partial<Message>);
    const md = formatThreadAsMarkdown(makeThread(), [hidden], {
      includeHidden: true,
    });
    expect(md).toContain("internal reminder");
  });
});

describe("formatThreadAsJSON opt-in flags", () => {
  /**
   * 覆盖“emits tool_calls field when includeToolCalls is true”这一可观察行为，防止相关边界在重构后回归。
   */
  it("emits tool_calls field when includeToolCalls is true", () => {
    const message = ai("ok", {
      tool_calls: [{ id: "1", name: "task", args: { description: "x" } }],
    } as Partial<Message>);
    const raw = formatThreadAsJSON(makeThread(), [message], {
      includeToolCalls: true,
    });
    expect(raw).toContain("tool_calls");
    expect(raw).toContain('"task"');
  });

  /**
   * 覆盖“keeps tool messages when includeToolMessages is true”这一可观察行为，防止相关边界在重构后回归。

   */

  it("keeps tool messages when includeToolMessages is true", () => {
    const raw = formatThreadAsJSON(
      makeThread(),
      [toolMsg("Task Succeeded. Result: keep me")],
      { includeToolMessages: true },
    );
    const parsed = JSON.parse(raw) as { messages: { type: string }[] };
    expect(parsed.messages.some((m) => m.type === "tool")).toBe(true);
    expect(raw).toContain("keep me");
  });
});

describe("formatThreadAsJSON", () => {
  /**
   * 覆盖“strips hidden messages, tool messages, reasoning, and tool calls”这一可观察行为，防止相关边界在重构后回归。
   */
  it("strips hidden messages, tool messages, reasoning, and tool calls", () => {
    const messages = [
      human("hello"),
      human("secret reminder", {
        additional_kwargs: { hide_from_ui: true },
      } as Partial<Message>),
      ai("answer", {
        additional_kwargs: {
          reasoning_content: "secret reasoning",
        },
        tool_calls: [{ id: "1", name: "task", args: {} }],
      } as Partial<Message>),
      toolMsg("internal trace"),
    ];
    const raw = formatThreadAsJSON(makeThread(), messages);
    const parsed = JSON.parse(raw) as {
      messages: { type: string; tool_calls?: unknown[] }[];
    };

    expect(parsed.messages).toHaveLength(2);
    expect(parsed.messages.every((m) => m.type !== "tool")).toBe(true);
    expect(raw).not.toContain("secret reminder");
    expect(raw).not.toContain("secret reasoning");
    expect(raw).not.toContain("internal trace");
    expect(raw).not.toContain("tool_calls");
  });

  /**
   * 覆盖“strips inline <think>...</think> wrappers from content”这一可观察行为，防止相关边界在重构后回归。

   */

  it("strips inline <think>...</think> wrappers from content", () => {
    // bytedance/deer-flow#3131 审查：JSON 导出必须运行 Markdown 路径使用的同一
    // 清理器，以确保即使 `includeReasoning` 保持默认 false，内联推理也绝不泄漏。
    const message = ai("<think>internal monologue</think>visible answer", {
      id: "ai-1",
    } as Partial<Message>);
    const raw = formatThreadAsJSON(makeThread(), [message]);
    expect(raw).not.toContain("internal monologue");
    expect(raw).not.toContain("<think>");
    expect(raw).toContain("visible answer");
  });

  /**
   * 覆盖“strips content-array thinking blocks from content”这一可观察行为，防止相关边界在重构后回归。

   */

  it("strips content-array thinking blocks from content", () => {
    const message = ai("placeholder", {
      id: "ai-2",
      content: [
        { type: "thinking", thinking: "hidden reasoning step" },
        { type: "text", text: "final visible text" },
      ],
    } as unknown as Partial<Message>);
    const raw = formatThreadAsJSON(makeThread(), [message]);
    expect(raw).not.toContain("hidden reasoning step");
    expect(raw).toContain("final visible text");
  });

  /**
   * 覆盖“strips <uploaded_files> markers from content”这一可观察行为，防止相关边界在重构后回归。

   */

  it("strips <uploaded_files> markers from content", () => {
    const message = human(
      "real prompt\n<uploaded_files>\n/mnt/user-data/uploads/secret.pdf\n</uploaded_files>",
      { id: "h-clean" } as Partial<Message>,
    );
    const raw = formatThreadAsJSON(makeThread(), [message]);
    expect(raw).not.toContain("<uploaded_files>");
    expect(raw).not.toContain("secret.pdf");
    expect(raw).toContain("real prompt");
  });

  /**
   * 覆盖“drops AI messages that sanitise to empty content”这一可观察行为，防止相关边界在重构后回归。

   */

  it("drops AI messages that sanitise to empty content", () => {
    // 纯推理 AI 片段（无可见文本、无工具调用）不应在导出中以 `{content: ""}` 行保留。
    const message = ai("<think>only thinking, no answer</think>", {
      id: "ai-3",
    } as Partial<Message>);
    const raw = formatThreadAsJSON(makeThread(), [message]);
    const parsed = JSON.parse(raw) as { messages: unknown[] };
    expect(parsed.messages).toHaveLength(0);
  });

  /**
   * 覆盖“strips <system-reminder>/<memory>/<current_date> as defence in depth”这一可观察行为，防止相关边界在重构后回归。

   */

  it("strips <system-reminder>/<memory>/<current_date> as defence in depth", () => {
    // 首要保护是 `isHiddenFromUIMessage` 过滤整个隐藏的 HumanMessage。若回归移除了
    // `hide_from_ui` 标志（或标记泄漏到原本可见的消息中），清理器在导出前仍必须
    // 清除该载荷。
    const leaky = human("real user text", {
      id: "leak-1",
      content:
        "<system-reminder>\n<memory>secret fact A</memory>\n<current_date>2026-01-01, Tuesday</current_date>\n</system-reminder>\nreal user text",
      // 故意不设置 hide_from_ui，以模拟深度防御清除逻辑所防范的回归场景。
    } as unknown as Partial<Message>);
    const raw = formatThreadAsJSON(makeThread(), [leaky]);
    expect(raw).not.toContain("<system-reminder>");
    expect(raw).not.toContain("<memory>");
    expect(raw).not.toContain("<current_date>");
    expect(raw).not.toContain("secret fact A");
    expect(raw).toContain("real user text");
  });

  /**
   * 覆盖“strips <slash_skill_activation> as defence in depth”这一可观察行为，防止相关边界在重构后回归。

   */

  it("strips <slash_skill_activation> as defence in depth", () => {
    // 斜杠激活通常位于隐藏的 HumanMessage 中。若回放或状态合并丢失该标志，导出仍
    // 不得将完整 SKILL.md 内容泄漏到用户可见的对话记录。
    const leaky = human("real user task", {
      id: "leak-slash-skill",
      content:
        "<slash_skill_activation>\n<skill_content># Secret SKILL.md\nUse internal source.</skill_content>\n</slash_skill_activation>\nreal user task",
    } as unknown as Partial<Message>);
    const raw = formatThreadAsJSON(makeThread(), [leaky]);
    expect(raw).not.toContain("<slash_skill_activation>");
    expect(raw).not.toContain("Secret SKILL.md");
    expect(raw).not.toContain("internal source");
    expect(raw).toContain("real user task");
  });

  /**
   * 覆盖“sanitises tool message content when includeToolMessages is true”这一可观察行为，防止相关边界在重构后回归。

   */

  it("sanitises tool message content when includeToolMessages is true", () => {
    const message = {
      id: "t-leak",
      type: "tool",
      content:
        "Task Succeeded. Result: payload\n<uploaded_files>\n/mnt/user-data/uploads/secret.pdf\n</uploaded_files>",
      name: "task",
      tool_call_id: "call-leak",
    } as unknown as Message;

    const raw = formatThreadAsJSON(makeThread(), [message], {
      includeToolMessages: true,
    });
    expect(raw).toContain("Task Succeeded");
    expect(raw).not.toContain("<uploaded_files>");
    expect(raw).not.toContain("secret.pdf");
  });

  /**
   * 覆盖“preserves text and image_url parts in mixed content arrays”这一可观察行为，防止相关边界在重构后回归。

   */

  it("preserves text and image_url parts in mixed content arrays", () => {
    // `extractContentFromMessage` 保留 `text` 和 `image_url` 部分，并丢弃
    // `thinking` 部分。JSON 导出必须遵守该契约。
    const message = ai("placeholder", {
      id: "ai-mixed",
      content: [
        { type: "thinking", thinking: "internal reasoning" },
        { type: "text", text: "user-visible answer" },
        {
          type: "image_url",
          image_url: { url: "https://example.invalid/cat.png" },
        },
      ],
    } as unknown as Partial<Message>);
    const raw = formatThreadAsJSON(makeThread(), [message]);
    expect(raw).toContain("user-visible answer");
    expect(raw).toContain("https://example.invalid/cat.png");
    expect(raw).not.toContain("internal reasoning");
  });

  /**
   * 覆盖“drops opted-in empty reasoning rather than emit reasoning: ''”这一可观察行为，防止相关边界在重构后回归。

   */

  it("drops opted-in empty reasoning rather than emit reasoning: ''", () => {
    // `extractReasoningContentFromMessage` 对没有推理内容的 AI 消息可以合法地返回
    // ""。导出必须镜像 Markdown 路径的 `!reasoning` `continue`，丢弃该行而不是
    // 泄漏 `{reasoning: ""}`。
    const message = ai("", {
      id: "ai-empty-reasoning",
      additional_kwargs: { reasoning_content: "" },
    } as Partial<Message>);
    const raw = formatThreadAsJSON(makeThread(), [message], {
      includeReasoning: true,
    });
    const parsed = JSON.parse(raw) as { messages: unknown[] };
    expect(parsed.messages).toHaveLength(0);
  });
});
