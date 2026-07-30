import type { Skill } from "@/core/skills";
export {
  SUGGESTION_TEMPLATE_PLACEHOLDER_PATTERN,
  findSuggestionTemplatePlaceholder,
} from "@/core/suggestions/placeholders";

export const MAX_SKILL_SUGGESTIONS = 6;

export type SlashSuggestion = {
  name: string;
  description: string;
  kind: "builtin" | "skill";
};

export type GoalCommand =
  | { kind: "status" }
  | { kind: "clear" }
  | { kind: "set"; objective: string };

export type InputSubmitAction =
  | { kind: "goal"; command: GoalCommand }
  | { kind: "compact" }
  | { kind: "stop" }
  | { kind: "empty" }
  | { kind: "message" };

export type GoalRequestState = {
  controller: AbortController | null;
  sequence: number;
  threadId: string | null;
};

export type ActiveGoalRequest = {
  controller: AbortController;
  sequence: number;
  threadId: string;
};

/** 创建用于隔离不同线程目标请求的本地状态。 */
export function createGoalRequestState(): GoalRequestState {
  return {
    controller: null,
    sequence: 0,
    threadId: null,
  };
}

/** 开始请求并递增令牌，使旧响应无法覆盖当前线程的状态。 */
export function beginGoalRequest(
  state: GoalRequestState,
  threadId: string,
): ActiveGoalRequest {
  state.controller?.abort();
  const controller = new AbortController();
  const request = {
    controller,
    sequence: state.sequence + 1,
    threadId,
  };
  state.controller = controller;
  state.sequence = request.sequence;
  state.threadId = threadId;
  return request;
}

/** 中止尚未完成的目标请求，避免卸载或切线程后的陈旧更新。 */
export function abortGoalRequest(state: GoalRequestState): void {
  state.controller?.abort();
  state.controller = null;
  state.sequence += 1;
  state.threadId = null;
}

/** 仅在请求仍为当前请求时清理其控制器。 */
export function finishGoalRequest(
  state: GoalRequestState,
  request: ActiveGoalRequest,
): void {
  if (
    state.controller === request.controller &&
    state.sequence === request.sequence
  ) {
    state.controller = null;
  }
}

/** 判断异步响应是否仍归属于当前线程和当前请求令牌。 */
export function isCurrentGoalRequest(
  state: GoalRequestState,
  request: ActiveGoalRequest,
  threadId: string,
): boolean {
  return (
    state.controller === request.controller &&
    state.sequence === request.sequence &&
    state.threadId === threadId &&
    !request.controller.signal.aborted
  );
}

/** 判断错误是否由主动中止请求引起。 */
export function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (typeof error === "object" &&
      error !== null &&
      Reflect.get(error, "name") === "AbortError")
  );
}

/** 从输入开头提取尚未提交的斜杠技能查询。 */
export function getLeadingSlashSkillQuery(value: string): string | null {
  if (!value.startsWith("/")) {
    return null;
  }

  const query = value.slice(1);
  if (query.includes("/") || /\s/.test(query)) {
    return null;
  }

  return query;
}

/** 按输入查询筛选并排序内置命令与技能建议。 */
export function getMatchingSkillSuggestions(
  skills: Skill[],
  query: string,
  builtinCommands: SlashSuggestion[],
): SlashSuggestion[] {
  const normalizedQuery = query.toLowerCase();
  const builtinCommandNames = new Set(
    builtinCommands.map(({ name }) => name.toLowerCase()),
  );

  const builtinMatches = builtinCommands.filter(({ name, description }) => {
    if (!normalizedQuery) {
      return true;
    }
    return (
      name.toLowerCase().includes(normalizedQuery) ||
      description.toLowerCase().includes(normalizedQuery)
    );
  });

  const skillMatches = skills
    .map((skill, index) => ({
      skill,
      index,
      name: skill.name.toLowerCase(),
    }))
    .filter(({ skill, name }) => {
      if (!skill.enabled) {
        return false;
      }
      if (builtinCommandNames.has(name)) {
        return false;
      }
      return !normalizedQuery || name.includes(normalizedQuery);
    })
    .sort((a, b) => {
      const aStartsWith = a.name.startsWith(normalizedQuery);
      const bStartsWith = b.name.startsWith(normalizedQuery);
      if (aStartsWith !== bStartsWith) {
        return aStartsWith ? -1 : 1;
      }
      return a.index - b.index;
    })
    .slice(0, MAX_SKILL_SUGGESTIONS)
    .map(({ skill }) => ({
      name: skill.name,
      description: skill.description,
      kind: "skill" as const,
    }));

  return [...skillMatches, ...builtinMatches].slice(0, MAX_SKILL_SUGGESTIONS);
}

/** 解析 `/goal` 命令及其设置、查询或清除意图。 */
export function parseGoalCommand(value: string): GoalCommand | null {
  const trimmed = value.trim();
  const match = /^\/goal(?:\s+|$)/i.exec(trimmed);
  if (!match) {
    return null;
  }

  const args = trimmed.slice(match[0].length).trim();
  if (!args) {
    return { kind: "status" };
  }
  if (["clear", "reset", "off"].includes(args.toLowerCase())) {
    return { kind: "clear" };
  }
  return { kind: "set", objective: args };
}

/** 判断输入是否为需要独立处理的 `/compact` 命令。 */
export function parseCompactCommand(value: string): boolean {
  return /^\/(?:compact|context\s+compact)\s*$/i.test(value.trim());
}

/** 判断草稿是否可交给输入润色流程处理。 */
export function canPolishInput(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) {
    return false;
  }
  // 保留的内置命令会路由到专属处理器而非 LLM，因此不能被改写。这里复用
  // 编辑器分发命令时使用的解析器，避免维护第三份并行的命令列表。
  return parseGoalCommand(trimmed) === null && !parseCompactCommand(trimmed);
}

/** 根据输入、命令与状态确定编辑器应执行的提交动作。 */
export function getInputSubmitAction({
  text,
  fileCount,
  status,
}: {
  text: string;
  fileCount: number;
  status: string;
}): InputSubmitAction {
  const goalCommand = parseGoalCommand(text);
  if (goalCommand && fileCount === 0) {
    return { kind: "goal", command: goalCommand };
  }
  if (parseCompactCommand(text) && fileCount === 0) {
    return { kind: "compact" };
  }
  if (status === "streaming") {
    return { kind: "stop" };
  }
  if (!text.trim() && fileCount === 0) {
    return { kind: "empty" };
  }
  return { kind: "message" };
}

/** 从目标接口响应中提取可展示的失败原因。 */
export async function readGoalResponseError(
  response: Response,
): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // 未获得详情时回退到通用提示。
  }
  return `HTTP ${response.status}`;
}
