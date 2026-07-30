import { describe, expect, it } from "@rstest/core";

import type { SubtaskStep } from "@/core/tasks/steps";
import {
  computeNextSubtask,
  isTerminalSubtaskStatus,
  subtaskNotification,
} from "@/core/tasks/subtask-update";
import type { Subtask } from "@/core/tasks/types";

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 baseTask 的约定。

 */

function baseTask(overrides: Partial<Subtask> = {}): Subtask {
  return {
    id: "t1",
    status: "in_progress",
    subagent_type: "general-purpose",
    description: "research",
    prompt: "do it",
    ...overrides,
  };
}

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 step 的约定。

 */

function step(message_index: number): SubtaskStep {
  return {
    kind: "tool",
    message_index,
    text: `step ${message_index}`,
    truncated: false,
  };
}

describe("computeNextSubtask", () => {
  /**
   * 覆盖“merges step deltas into the provided previous, preserving both”这一可观察行为，防止相关边界在重构后回归。
   */
  it("merges step deltas into the provided previous, preserving both", () => {
    const previous = baseTask({ steps: [step(1), step(2)] });

    const { next } = computeNextSubtask(previous, {
      id: "t1",
      steps: [step(3)],
    });

    // #3779 的过期闭包竞争回归：next 从传入的任意 `previous`（函数式更新的最新状态）
    // 推导，因此并发到达的步骤会被保留，不会被延迟完成的回填覆盖。
    expect(next.steps?.map((s) => s.message_index)).toEqual([1, 2, 3]);
  });

  /**
   * 覆盖“does not drop steps present only on the latest previous”这一可观察行为，防止相关边界在重构后回归。

   */

  it("does not drop steps present only on the latest previous", () => {
    // 模拟回填触发时 previous 有 0 个步骤，但它完成时最新 previous 已有 SSE 步骤 1..2。
    // 回填带来历史步骤 1..3；合并必须保留全部步骤，而不是重置为 []。
    const latestPrevious = baseTask({ steps: [step(1), step(2)] });

    const { next } = computeNextSubtask(latestPrevious, {
      id: "t1",
      steps: [step(1), step(2), step(3)],
    });

    expect(next.steps?.map((s) => s.message_index)).toEqual([1, 2, 3]);
  });

  /**
   * 覆盖“keeps the latest cumulative token snapshot when an older event arrives late”这一可观察行为，防止相关边界在重构后回归。

   */

  it("keeps the latest cumulative token snapshot when an older event arrives late", () => {
    const previous = baseTask({
      usage: { inputTokens: 200, outputTokens: 40, totalTokens: 240 },
    });

    const { next } = computeNextSubtask(previous, {
      id: "t1",
      usage: { inputTokens: 100, outputTokens: 20, totalTokens: 120 },
    });

    expect(next.usage).toEqual({
      inputTokens: 200,
      outputTokens: 40,
      totalTokens: 240,
    });
  });

  /**
   * 覆盖“keeps a terminal status stable against a late in_progress write”这一可观察行为，防止相关边界在重构后回归。

   */

  it("keeps a terminal status stable against a late in_progress write", () => {
    const previous = baseTask({ status: "completed" });

    const { next, becameTerminal } = computeNextSubtask(previous, {
      id: "t1",
      status: "in_progress",
    });

    expect(next.status).toBe("completed");
    expect(becameTerminal).toBe(false);
  });

  /**
   * 覆盖“flags becameTerminal on the first transition to a terminal status”这一可观察行为，防止相关边界在重构后回归。

   */

  it("flags becameTerminal on the first transition to a terminal status", () => {
    const previous = baseTask({ status: "in_progress" });

    const { next, becameTerminal } = computeNextSubtask(previous, {
      id: "t1",
      status: "completed",
      result: "done",
    });

    expect(next.status).toBe("completed");
    expect(next.result).toBe("done");
    expect(becameTerminal).toBe(true);
  });

  /**
   * 覆盖“handles an undefined previous (first write for a task)”这一可观察行为，防止相关边界在重构后回归。

   */

  it("handles an undefined previous (first write for a task)", () => {
    const { next, becameTerminal } = computeNextSubtask(undefined, {
      id: "t1",
      status: "in_progress",
      subagent_type: "bash",
      description: "run",
      prompt: "p",
      steps: [step(1)],
    });

    expect(next.id).toBe("t1");
    expect(next.steps?.map((s) => s.message_index)).toEqual([1]);
    expect(becameTerminal).toBe(false);
  });

  /**
   * 覆盖“reports changed=false when a terminal update carries identical runtime metadata”这一可观察行为，防止相关边界在重构后回归。

   */

  it("reports changed=false when a terminal update carries identical runtime metadata", () => {
    // 每次 MessageList 渲染都会重新解析终止 ToolMessage，因此相同的 modelName/usage
    // 每次都作为一个*新*对象再次到达。值相等的重复应用不得被标记为变化，否则卡片会
    // 无限循环。
    const previous = baseTask({
      status: "completed",
      result: "done",
      modelName: "opus",
      usage: { inputTokens: 100, outputTokens: 20, totalTokens: 120 },
    });

    const { changed } = computeNextSubtask(previous, {
      id: "t1",
      status: "completed",
      result: "done",
      modelName: "opus",
      usage: { inputTokens: 100, outputTokens: 20, totalTokens: 120 },
    });

    expect(changed).toBe(false);
  });

  /**
   * 覆盖“reports changed=true when runtime metadata actually differs”这一可观察行为，防止相关边界在重构后回归。

   */

  it("reports changed=true when runtime metadata actually differs", () => {
    const previous = baseTask({
      status: "completed",
      modelName: "opus",
      usage: { inputTokens: 100, outputTokens: 20, totalTokens: 120 },
    });

    const { changed } = computeNextSubtask(previous, {
      id: "t1",
      status: "completed",
      modelName: "opus",
      usage: { inputTokens: 300, outputTokens: 60, totalTokens: 360 },
    });

    expect(changed).toBe(true);
  });
});

describe("subtaskNotification", () => {
  /**
   * 覆盖“defers a terminal transition (arrives during render, must not setState mid-render)”这一可观察行为，防止相关边界在重构后回归。
   */
  it("defers a terminal transition (arrives during render, must not setState mid-render)", () => {
    expect(
      subtaskNotification(
        { id: "t1", status: "completed", modelName: "opus" },
        { becameTerminal: true, changed: true },
      ),
    ).toBe("deferred");
  });

  /**
   * 覆盖“eagerly reflects a live SSE update that actually changed”这一可观察行为，防止相关边界在重构后回归。

   */

  it("eagerly reflects a live SSE update that actually changed", () => {
    expect(
      subtaskNotification(
        {
          id: "t1",
          usage: { inputTokens: 300, outputTokens: 60, totalTokens: 360 },
        },
        { becameTerminal: false, changed: true },
      ),
    ).toBe("eager");
  });

  /**
   * 覆盖“does nothing when a re-parsed terminal result carries unchanged metadata”这一可观察行为，防止相关边界在重构后回归。

   */

  it("does nothing when a re-parsed terminal result carries unchanged metadata", () => {
    // 回归场景：每次重新解析终止消息时均有 modelName/usage，但状态未改变。在此触发
    // setTasks 就会形成渲染循环（P1）。
    expect(
      subtaskNotification(
        {
          id: "t1",
          status: "completed",
          modelName: "opus",
          usage: { inputTokens: 100, outputTokens: 20, totalTokens: 120 },
        },
        { becameTerminal: false, changed: false },
      ),
    ).toBe("none");
  });

  /**
   * 覆盖“does nothing when a replayed SSE usage snapshot did not change state”这一可观察行为，防止相关边界在重构后回归。

   */

  it("does nothing when a replayed SSE usage snapshot did not change state", () => {
    expect(
      subtaskNotification(
        {
          id: "t1",
          usage: { inputTokens: 100, outputTokens: 20, totalTokens: 120 },
        },
        { becameTerminal: false, changed: false },
      ),
    ).toBe("none");
  });
});

describe("isTerminalSubtaskStatus", () => {
  /**
   * 覆盖“recognizes terminal statuses only”这一可观察行为，防止相关边界在重构后回归。
   */
  it("recognizes terminal statuses only", () => {
    expect(isTerminalSubtaskStatus("completed")).toBe(true);
    expect(isTerminalSubtaskStatus("failed")).toBe(true);
    expect(isTerminalSubtaskStatus("in_progress")).toBe(false);
    expect(isTerminalSubtaskStatus(undefined)).toBe(false);
  });
});
