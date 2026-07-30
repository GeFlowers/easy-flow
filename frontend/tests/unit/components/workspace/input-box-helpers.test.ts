import { describe, expect, it } from "@rstest/core";

import {
  abortGoalRequest,
  beginGoalRequest,
  canPolishInput,
  createGoalRequestState,
  findSuggestionTemplatePlaceholder,
  finishGoalRequest,
  getInputSubmitAction,
  getLeadingSlashSkillQuery,
  getMatchingSkillSuggestions,
  isAbortError,
  isCurrentGoalRequest,
  parseCompactCommand,
  parseGoalCommand,
  readGoalResponseError,
  type SlashSuggestion,
} from "@/components/workspace/input-box-helpers";
import type { Skill } from "@/core/skills";

/**
 * 构造测试所需的稳定夹具，使调用处能够明确复用 makeSkill 的约定。

 */

function makeSkill(name: string, enabled = true): Skill {
  return {
    name,
    description: `${name} description`,
    enabled,
  } as Skill;
}

// 内置命令名称不带前导斜杠；输入框会将其渲染为 `/${name}`。此处保持相同形式。
const builtins: SlashSuggestion[] = [
  {
    name: "goal",
    description: "Set, show, or clear an active goal",
    kind: "builtin",
  },
  { name: "new", description: "Start a new thread", kind: "builtin" },
];

describe("parseGoalCommand", () => {
  /**
   * 覆盖“returns status for a bare /goal”这一可观察行为，防止相关边界在重构后回归。
   */
  it("returns status for a bare /goal", () => {
    expect(parseGoalCommand("/goal")).toEqual({ kind: "status" });
    expect(parseGoalCommand("  /goal   ")).toEqual({ kind: "status" });
  });

  /**
   * 覆盖“treats clear/reset/off as clear (case-insensitive)”这一可观察行为，防止相关边界在重构后回归。

   */

  it("treats clear/reset/off as clear (case-insensitive)", () => {
    expect(parseGoalCommand("/goal clear")).toEqual({ kind: "clear" });
    expect(parseGoalCommand("/GOAL Reset")).toEqual({ kind: "clear" });
    expect(parseGoalCommand("/goal off")).toEqual({ kind: "clear" });
  });

  /**
   * 覆盖“captures the objective for /goal <text>”这一可观察行为，防止相关边界在重构后回归。

   */

  it("captures the objective for /goal <text>", () => {
    expect(parseGoalCommand("/goal ship the feature")).toEqual({
      kind: "set",
      objective: "ship the feature",
    });
  });

  /**
   * 覆盖“returns null when the input is not a /goal command”这一可观察行为，防止相关边界在重构后回归。

   */

  it("returns null when the input is not a /goal command", () => {
    expect(parseGoalCommand("/goalkeeper do thing")).toBeNull();
    expect(parseGoalCommand("hello")).toBeNull();
    expect(parseGoalCommand("/new")).toBeNull();
  });
});

describe("parseCompactCommand", () => {
  /**
   * 覆盖“matches compact commands”这一可观察行为，防止相关边界在重构后回归。
   */
  it("matches compact commands", () => {
    expect(parseCompactCommand("/compact")).toBe(true);
    expect(parseCompactCommand(" /context compact ")).toBe(true);
    expect(parseCompactCommand("/CONTEXT   COMPACT")).toBe(true);
  });

  /**
   * 覆盖“rejects non-compact commands”这一可观察行为，防止相关边界在重构后回归。

   */

  it("rejects non-compact commands", () => {
    expect(parseCompactCommand("/compact now")).toBe(false);
    expect(parseCompactCommand("/context")).toBe(false);
    expect(parseCompactCommand("compact")).toBe(false);
  });
});

describe("getInputSubmitAction", () => {
  /**
   * 覆盖“handles /goal commands before the streaming stop shortcut”这一可观察行为，防止相关边界在重构后回归。
   */
  it("handles /goal commands before the streaming stop shortcut", () => {
    expect(
      getInputSubmitAction({
        text: "/goal ",
        fileCount: 0,
        status: "streaming",
      }),
    ).toEqual({ kind: "goal", command: { kind: "status" } });
  });

  /**
   * 覆盖“handles /goal set commands before the streaming stop shortcut”这一可观察行为，防止相关边界在重构后回归。

   */

  it("handles /goal set commands before the streaming stop shortcut", () => {
    expect(
      getInputSubmitAction({
        text: "/goal finish the work",
        fileCount: 0,
        status: "streaming",
      }),
    ).toEqual({
      kind: "goal",
      command: { kind: "set", objective: "finish the work" },
    });
  });

  /**
   * 覆盖“keeps ordinary streaming submits as stop”这一可观察行为，防止相关边界在重构后回归。

   */

  it("keeps ordinary streaming submits as stop", () => {
    expect(
      getInputSubmitAction({
        text: "hello",
        fileCount: 0,
        status: "streaming",
      }),
    ).toEqual({ kind: "stop" });
  });

  /**
   * 覆盖“does not treat /goal text with attachments as a goal command”这一可观察行为，防止相关边界在重构后回归。

   */

  it("does not treat /goal text with attachments as a goal command", () => {
    expect(
      getInputSubmitAction({
        text: "/goal ",
        fileCount: 1,
        status: "ready",
      }),
    ).toEqual({ kind: "message" });
  });

  /**
   * 覆盖“handles compact commands”这一可观察行为，防止相关边界在重构后回归。

   */

  it("handles compact commands", () => {
    expect(
      getInputSubmitAction({
        text: "/compact",
        fileCount: 0,
        status: "ready",
      }),
    ).toEqual({ kind: "compact" });
    expect(
      getInputSubmitAction({
        text: "/context compact",
        fileCount: 0,
        status: "ready",
      }),
    ).toEqual({ kind: "compact" });
  });

  /**
   * 覆盖“does not treat compact commands with attachments as compact”这一可观察行为，防止相关边界在重构后回归。

   */

  it("does not treat compact commands with attachments as compact", () => {
    expect(
      getInputSubmitAction({
        text: "/compact",
        fileCount: 1,
        status: "ready",
      }),
    ).toEqual({ kind: "message" });
  });

  /**
   * 覆盖“ignores empty ready submits”这一可观察行为，防止相关边界在重构后回归。

   */

  it("ignores empty ready submits", () => {
    expect(
      getInputSubmitAction({
        text: "   ",
        fileCount: 0,
        status: "ready",
      }),
    ).toEqual({ kind: "empty" });
  });
});

describe("canPolishInput", () => {
  /**
   * 覆盖“requires non-empty input”这一可观察行为，防止相关边界在重构后回归。
   */
  it("requires non-empty input", () => {
    expect(canPolishInput("")).toBe(false);
    expect(canPolishInput("   ")).toBe(false);
  });

  /**
   * 覆盖“allows ordinary text and slash skill prompts”这一可观察行为，防止相关边界在重构后回归。

   */

  it("allows ordinary text and slash skill prompts", () => {
    expect(canPolishInput("make this clearer")).toBe(true);
    expect(canPolishInput("/web-dev build a polished page")).toBe(true);
    expect(canPolishInput("/goalkeeper do thing")).toBe(true);
    expect(canPolishInput("/helper explain this")).toBe(true);
    // `/help` 并非输入框中的真实内置命令，因此它和其他斜杠技能提示词一样
    // 保持可用。
    expect(canPolishInput("/help")).toBe(true);
    expect(canPolishInput("/help me")).toBe(true);
  });

  /**
   * 覆盖“blocks reserved builtin commands”这一可观察行为，防止相关边界在重构后回归。

   */

  it("blocks reserved builtin commands", () => {
    expect(canPolishInput("/goal")).toBe(false);
    expect(canPolishInput("/goal ship this feature")).toBe(false);
    expect(canPolishInput("/goal clear")).toBe(false);
    expect(canPolishInput("/compact")).toBe(false);
    expect(canPolishInput("/context compact")).toBe(false);
  });
});

describe("getLeadingSlashSkillQuery", () => {
  /**
   * 覆盖“returns the query for a leading slash token”这一可观察行为，防止相关边界在重构后回归。
   */
  it("returns the query for a leading slash token", () => {
    expect(getLeadingSlashSkillQuery("/rev")).toBe("rev");
    expect(getLeadingSlashSkillQuery("/")).toBe("");
  });

  /**
   * 覆盖“returns null when there is no leading slash or the token is not bare”这一可观察行为，防止相关边界在重构后回归。

   */

  it("returns null when there is no leading slash or the token is not bare", () => {
    expect(getLeadingSlashSkillQuery("rev")).toBeNull();
    expect(getLeadingSlashSkillQuery("/rev now")).toBeNull();
    expect(getLeadingSlashSkillQuery("/a/b")).toBeNull();
  });
});

describe("getMatchingSkillSuggestions", () => {
  /**
   * 覆盖“excludes disabled skills and ranks prefix matches first”这一可观察行为，防止相关边界在重构后回归。
   */
  it("excludes disabled skills and ranks prefix matches first", () => {
    const skills = [
      makeSkill("deep-research"),
      makeSkill("review"),
      makeSkill("reviewer-disabled", false),
    ];

    const result = getMatchingSkillSuggestions(skills, "rev", []);

    expect(result.map((s) => s.name)).toEqual(["review"]);
    expect(result.every((s) => s.kind === "skill")).toBe(true);
  });

  /**
   * 覆盖“includes matching builtin commands after skills”这一可观察行为，防止相关边界在重构后回归。

   */

  it("includes matching builtin commands after skills", () => {
    const result = getMatchingSkillSuggestions(
      [makeSkill("goal-helper")],
      "goal",
      builtins,
    );

    expect(result.map((s) => s.name)).toContain("goal-helper");
    expect(result.map((s) => s.name)).toContain("goal");
  });

  /**
   * 覆盖“excludes skills that collide with builtin command names”这一可观察行为，防止相关边界在重构后回归。

   */

  it("excludes skills that collide with builtin command names", () => {
    const result = getMatchingSkillSuggestions(
      [makeSkill("goal"), makeSkill("goal-helper")],
      "goal",
      builtins,
    );

    expect(result.map((s) => `${s.kind}:${s.name}`)).toEqual([
      "skill:goal-helper",
      "builtin:goal",
    ]);
  });

  /**
   * 覆盖“caps the number of suggestions”这一可观察行为，防止相关边界在重构后回归。

   */

  it("caps the number of suggestions", () => {
    const skills = Array.from({ length: 10 }, (_, i) =>
      makeSkill(`skill-${i}`),
    );
    const result = getMatchingSkillSuggestions(skills, "", []);
    expect(result.length).toBeLessThanOrEqual(6);
  });
});

describe("readGoalResponseError", () => {
  /**
   * 覆盖“returns the detail string when present”这一可观察行为，防止相关边界在重构后回归。
   */
  it("returns the detail string when present", async () => {
    const response = {
      status: 422,
      json: async () => ({ detail: "Goal objective must not be empty." }),
    } as unknown as Response;
    expect(await readGoalResponseError(response)).toBe(
      "Goal objective must not be empty.",
    );
  });

  /**
   * 覆盖“falls back to the HTTP status when detail is missing or unparseable”这一可观察行为，防止相关边界在重构后回归。

   */

  it("falls back to the HTTP status when detail is missing or unparseable", async () => {
    const noDetail = {
      status: 500,
      json: async () => ({}),
    } as unknown as Response;
    expect(await readGoalResponseError(noDetail)).toBe("HTTP 500");

    const broken = {
      status: 503,
      json: async () => {
        throw new Error("not json");
      },
    } as unknown as Response;
    expect(await readGoalResponseError(broken)).toBe("HTTP 503");
  });
});

describe("goal request lifecycle", () => {
  /**
   * 覆盖“aborts a pending goal request when the thread changes and blocks stale updates”这一可观察行为，防止相关边界在重构后回归。
   */
  it("aborts a pending goal request when the thread changes and blocks stale updates", () => {
    const state = createGoalRequestState();
    const first = beginGoalRequest(state, "thread-1");
    const updates: string[] = [];

    abortGoalRequest(state);
    const second = beginGoalRequest(state, "thread-2");

    if (isCurrentGoalRequest(state, first, "thread-1")) {
      updates.push("thread-1");
    }
    if (isCurrentGoalRequest(state, second, "thread-2")) {
      updates.push("thread-2");
    }

    expect(first.controller.signal.aborted).toBe(true);
    expect(second.controller.signal.aborted).toBe(false);
    expect(updates).toEqual(["thread-2"]);
  });

  /**
   * 覆盖“does not let an older request finish a newer one”这一可观察行为，防止相关边界在重构后回归。

   */

  it("does not let an older request finish a newer one", () => {
    const state = createGoalRequestState();
    const first = beginGoalRequest(state, "thread-1");
    const second = beginGoalRequest(state, "thread-1");

    finishGoalRequest(state, first);

    expect(isCurrentGoalRequest(state, second, "thread-1")).toBe(true);
  });

  /**
   * 覆盖“recognizes abort-shaped errors”这一可观察行为，防止相关边界在重构后回归。

   */

  it("recognizes abort-shaped errors", () => {
    expect(isAbortError(new DOMException("aborted", "AbortError"))).toBe(true);
    expect(
      isAbortError(Object.assign(new Error("aborted"), { name: "AbortError" })),
    ).toBe(true);
    expect(isAbortError(new Error("other"))).toBe(false);
  });

  /**
   * 覆盖“supports compact request staleness guards with the same lifecycle”这一可观察行为，防止相关边界在重构后回归。

   */

  it("supports compact request staleness guards with the same lifecycle", () => {
    const state = createGoalRequestState();
    const compact = beginGoalRequest(state, "thread-1");

    const replacement = beginGoalRequest(state, "thread-1");

    expect(compact.controller.signal.aborted).toBe(true);
    expect(isCurrentGoalRequest(state, compact, "thread-1")).toBe(false);
    expect(isCurrentGoalRequest(state, replacement, "thread-1")).toBe(true);

    finishGoalRequest(state, replacement);

    expect(isCurrentGoalRequest(state, replacement, "thread-1")).toBe(false);
  });
});

describe("findSuggestionTemplatePlaceholder", () => {
  /**
   * 覆盖“locates a topic/source placeholder”这一可观察行为，防止相关边界在重构后回归。
   */
  it("locates a topic/source placeholder", () => {
    const found = findSuggestionTemplatePlaceholder("Research [topic] deeply");
    expect(found).not.toBeNull();
    expect(
      found && "Research [topic] deeply".slice(found.start, found.end),
    ).toBe("[topic]");
  });

  /**
   * 覆盖“returns null when no placeholder is present”这一可观察行为，防止相关边界在重构后回归。

   */

  it("returns null when no placeholder is present", () => {
    expect(findSuggestionTemplatePlaceholder("no placeholder here")).toBeNull();
  });
});
