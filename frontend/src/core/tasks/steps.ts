/**
 * 实时（SSE）与重载（拉取）路径共享的子任务步骤模型。
 *
 * #3779 之前子任务卡片仅保留最新子代理消息，早期步骤一闪而过，重载后也无法恢复。`SubtaskStep` 是
 * 经规范化、可渲染的子代理进度单元：一条助手轮次（`kind: "ai"`，含工具调用请求）或一条工具结果
 * （`kind: "tool"`，含工具输出）。后端以同样形状持久化 `subagent.step` 运行事件内容；实时
 * `task_running` 仍携带原始消息，`messageToStep` 为其镜像转换。
 */

/** 子任务步骤中记录的单次工具调用请求。 */
export interface SubtaskStepToolCall {
  name?: string;
  args?: unknown;
}

/** 可渲染的子代理进度步骤，按消息序号维持时间线顺序。 */
export interface SubtaskStep {
  message_index: number;
  kind: "ai" | "tool";
  text: string;
  truncated?: boolean;
  tool_calls?: SubtaskStepToolCall[];
  tool_name?: string;
}

type RawMessage = {
  type?: string;
  content?: unknown;
  name?: string;
  tool_calls?: { name?: string; args?: unknown; [key: string]: unknown }[];
  [key: string]: unknown;
};

/** 将不同形态的消息内容收敛为用于步骤展示的纯文本。 */
function contentToText(content: unknown): string {
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content)) {
    return content
      .map((block) => {
        if (typeof block === "string") {
          return block;
        }
        if (block && typeof block === "object" && "text" in block) {
          const text = (block as { text?: unknown }).text;
          return typeof text === "string" ? text : "";
        }
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }
  return "";
}

/** 将实时 `task_running` 载荷中的原始子代理消息规范化为步骤。 */
export function messageToStep(
  message: RawMessage,
  messageIndex: number,
): SubtaskStep {
  const kind = message.type === "tool" ? "tool" : "ai";
  const step: SubtaskStep = {
    message_index: messageIndex,
    kind,
    text: contentToText(message.content),
  };

  if (kind === "tool") {
    step.tool_name = message.name;
  } else {
    step.tool_calls = (message.tool_calls ?? []).map((call) => ({
      name: call.name,
      args: call.args,
    }));
  }

  return step;
}

/**
 * 子任务卡片时间线要渲染的步骤（#3779），按 `message_index` 交错排列子代理助手轮次与工具步骤：
 *
 * - 始终保留工具步骤（每项均显示一行“子代理运行了 <tool>”）；
 * - 仅含可见推理文本时保留 AI 步骤；只请求工具的空文本轮次不比后续工具行提供更多信息，故丢弃；
 * - 任务为 `completed` 时，无 `tool_calls` 的尾部 AI 步骤即子代理最终回答，卡片已通过 `task.result`
 *   渲染，故此处丢弃以避免重复显示。
 */
export function stepsForDisplay(
  steps: SubtaskStep[] | undefined,
  status: "in_progress" | "completed" | "failed",
): SubtaskStep[] {
  const visible = (steps ?? [])
    .filter((step) => step.kind === "tool" || step.text.trim() !== "")
    .sort((a, b) => a.message_index - b.message_index);

  if (status === "completed") {
    const last = visible[visible.length - 1];
    if (last?.kind === "ai" && !last?.tool_calls?.length) {
      return visible.slice(0, -1);
    }
  }
  return visible;
}

type RunEvent = {
  event_type?: string;
  content?: unknown;
  metadata?: { task_id?: string } & Record<string, unknown>;
};

/**
 * 将 `GET /{rid}/events` 返回的持久化运行事件映射为子任务步骤，仅保留该 `taskId` 的
 * `subagent.step` 事件并按 message_index 排序。持久化 `content` 已符合步骤形状（由后端
 * `build_subagent_step` 生成），因此这里只进行过滤、投影和排序（#3779）。
 */
export function eventsToSteps(
  events: RunEvent[],
  taskId: string,
): SubtaskStep[] {
  const steps: SubtaskStep[] = [];
  for (const event of events) {
    if (event.event_type !== "subagent.step") {
      continue;
    }
    const content = event.content as
      | (SubtaskStep & { task_id?: string })
      | undefined;
    const eventTaskId = content?.task_id ?? event.metadata?.task_id;
    if (!content || eventTaskId !== taskId) {
      continue;
    }
    steps.push({
      message_index: content.message_index,
      kind: content.kind,
      text: content.text ?? "",
      truncated: content.truncated,
      tool_calls: content.tool_calls,
      tool_name: content.tool_name,
    });
  }
  return steps.sort((a, b) => a.message_index - b.message_index);
}

/**
 * 将 `incoming` 步骤合并到 `existing`，按 `message_index` 去重（以 incoming 为准）并保持排序。
 * 用于协调实时 SSE 步骤与展开时拉取的步骤，避免共享索引重复渲染。
 */
export function mergeSteps(
  existing: SubtaskStep[],
  incoming: SubtaskStep[],
): SubtaskStep[] {
  const byIndex = new Map<number, SubtaskStep>();
  for (const step of existing) {
    byIndex.set(step.message_index, step);
  }
  for (const step of incoming) {
    byIndex.set(step.message_index, step);
  }
  return [...byIndex.values()].sort(
    (a, b) => a.message_index - b.message_index,
  );
}
