import type { Message } from "@langchain/langgraph-sdk";

/** 人工输入请求支持的交互方式。 */
export type HumanInputMode =
  | "free_text"
  | "single_choice"
  | "choice_with_other";

/** 人工输入选择项的稳定标识、展示标签和提交值。 */
export type HumanInputOption = {
  id: string;
  label: string;
  value: string;
};

/** 后端通过工具消息 artifact.human_input 传递的人工输入请求协议。 */
export type HumanInputRequest = {
  version: 1;
  kind: "human_input_request";
  source: "ask_clarification" | string;
  request_id: string;
  tool_call_id?: string;
  clarification_type?: string;
  title?: string;
  question: string;
  context?: string | null;
  input_mode: HumanInputMode;
  options?: HumanInputOption[];
};

/** 用户对人工输入请求提交的选项或自由文本响应协议。 */
export type HumanInputResponse =
  | {
      version: 1;
      kind: "human_input_response";
      source: string;
      request_id: string;
      response_kind: "option";
      option_id: string;
      value: string;
    }
  | {
      version: 1;
      kind: "human_input_response";
      source: string;
      request_id: string;
      response_kind: "text";
      value: string;
    };

/** 由消息历史推导出的人工输入状态，用于判断已答请求与最新待答请求。 */
export type HumanInputThreadState = {
  answeredResponses: Map<string, HumanInputResponse>;
  latestOpenRequestId: string | null;
};

/** 当新的线程错误出现且仍有待答请求时，判断是否应清除待答人工输入状态。 */
export function shouldClearPendingHumanInputOnThreadError({
  currentError,
  pendingRequestCount,
  previousError,
}: {
  currentError: unknown;
  pendingRequestCount: number;
  previousError: unknown;
}) {
  return (
    pendingRequestCount > 0 &&
    currentError != null &&
    !Object.is(currentError, previousError)
  );
}

/** 确认未知输入是非空、非数组对象，以便继续校验请求字段。 */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** 确认值为含有非空白字符的字符串。 */
function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

/** 限定交互模式为支持的自由文本、单选或带补充文本选项。 */
function isHumanInputMode(value: unknown): value is HumanInputMode {
  return (
    value === "free_text" ||
    value === "single_choice" ||
    value === "choice_with_other"
  );
}

/** 仅在未知值确为字符串时保留它，供中断请求字段校验使用。 */
function readOptionalString(value: unknown) {
  return typeof value === "string" ? value : undefined;
}

/** 校验选项数组中每一项的标识和显示文本，拒绝结构不完整的数据。 */
function parseOptions(value: unknown): HumanInputOption[] | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (!Array.isArray(value)) {
    return undefined;
  }

  const options: HumanInputOption[] = [];
  for (const option of value) {
    if (!isRecord(option)) {
      return undefined;
    }
    const id = option.id;
    const label = option.label;
    const optionValue = option.value;
    if (
      !isNonEmptyString(id) ||
      !isNonEmptyString(label) ||
      typeof optionValue !== "string"
    ) {
      return undefined;
    }
    options.push({ id, label, value: optionValue });
  }
  return options;
}

/** 校验未知载荷并解析为人工输入请求；不符合协议时返回 null。 */
export function parseHumanInputRequest(
  value: unknown,
): HumanInputRequest | null {
  if (!isRecord(value)) {
    return null;
  }
  if (
    value.version !== 1 ||
    value.kind !== "human_input_request" ||
    !isNonEmptyString(value.source) ||
    !isNonEmptyString(value.request_id) ||
    !isNonEmptyString(value.question) ||
    !isHumanInputMode(value.input_mode)
  ) {
    return null;
  }

  const options = parseOptions(value.options);
  if (value.options !== undefined && options === undefined) {
    return null;
  }
  if (
    (value.input_mode === "single_choice" ||
      value.input_mode === "choice_with_other") &&
    (!options || options.length === 0)
  ) {
    return null;
  }

  const context = value.context;
  if (
    context !== undefined &&
    context !== null &&
    typeof context !== "string"
  ) {
    return null;
  }

  return {
    version: 1,
    kind: "human_input_request",
    source: value.source,
    request_id: value.request_id,
    ...(readOptionalString(value.tool_call_id)
      ? { tool_call_id: readOptionalString(value.tool_call_id) }
      : {}),
    ...(readOptionalString(value.clarification_type)
      ? { clarification_type: readOptionalString(value.clarification_type) }
      : {}),
    ...(readOptionalString(value.title)
      ? { title: readOptionalString(value.title) }
      : {}),
    question: value.question,
    ...(context !== undefined ? { context } : {}),
    input_mode: value.input_mode,
    ...(options ? { options } : {}),
  };
}

/** 校验未知载荷并解析为人工输入响应；不符合协议时返回 null。 */
export function parseHumanInputResponse(
  value: unknown,
): HumanInputResponse | null {
  if (!isRecord(value)) {
    return null;
  }
  if (
    value.version !== 1 ||
    value.kind !== "human_input_response" ||
    !isNonEmptyString(value.source) ||
    !isNonEmptyString(value.request_id) ||
    !isNonEmptyString(value.value)
  ) {
    return null;
  }

  if (value.response_kind === "option") {
    if (!isNonEmptyString(value.option_id)) {
      return null;
    }
    return {
      version: 1,
      kind: "human_input_response",
      source: value.source,
      request_id: value.request_id,
      response_kind: "option",
      option_id: value.option_id,
      value: value.value,
    };
  }

  if (value.response_kind === "text") {
    return {
      version: 1,
      kind: "human_input_response",
      source: value.source,
      request_id: value.request_id,
      response_kind: "text",
      value: value.value,
    };
  }

  return null;
}

/** 从工具消息的 artifact.human_input 中提取人工输入请求。 */
export function extractHumanInputRequest(
  message: Message,
): HumanInputRequest | null {
  if (message.type !== "tool") {
    return null;
  }
  const artifact = Reflect.get(message, "artifact");
  if (!isRecord(artifact)) {
    return null;
  }
  return parseHumanInputRequest(artifact.human_input);
}

/** 从隐藏的人类消息 additional_kwargs 中提取人工输入响应。 */
export function extractHumanInputResponse(
  message: Message,
): HumanInputResponse | null {
  if (message.type !== "human") {
    return null;
  }
  const additionalKwargs = message.additional_kwargs;
  if (!isRecord(additionalKwargs)) {
    return null;
  }
  return parseHumanInputResponse(additionalKwargs.human_input_response);
}

/** 根据可见性规则和全部消息推导已答响应及最新待答请求。 */
export function deriveHumanInputThreadState(
  messages: Message[],
  isVisibleMessage: (message: Message) => boolean = (message) =>
    message.additional_kwargs?.hide_from_ui !== true,
): HumanInputThreadState {
  const answeredResponses = new Map<string, HumanInputResponse>();
  const seenRequestIds = new Set<string>();
  const requestOrder: string[] = [];

  for (const message of messages) {
    if (isVisibleMessage(message)) {
      const request = extractHumanInputRequest(message);
      if (request) {
        seenRequestIds.add(request.request_id);
        requestOrder.push(request.request_id);
      }
    }

    const response = extractHumanInputResponse(message);
    if (
      response &&
      seenRequestIds.has(response.request_id) &&
      !answeredResponses.has(response.request_id)
    ) {
      answeredResponses.set(response.request_id, response);
    }
  }

  const latestOpenRequestId =
    [...requestOrder]
      .reverse()
      .find((requestId) => !answeredResponses.has(requestId)) ?? null;

  return { answeredResponses, latestOpenRequestId };
}

/** 判断消息历史中是否仍存在未回答的人工输入请求。 */
export function hasOpenHumanInputRequest(
  messages: Message[],
  isVisibleMessage?: (message: Message) => boolean,
) {
  return (
    deriveHumanInputThreadState(messages, isVisibleMessage)
      .latestOpenRequestId !== null
  );
}

/** 根据选定选项构建与请求关联的人工输入响应。 */
export function createHumanInputOptionResponse(
  request: HumanInputRequest,
  option: HumanInputOption,
): HumanInputResponse {
  return {
    version: 1,
    kind: "human_input_response",
    source: request.source,
    request_id: request.request_id,
    response_kind: "option",
    option_id: option.id,
    value: option.value,
  };
}

/** 根据自由文本构建与请求关联的人工输入响应。 */
export function createHumanInputTextResponse(
  request: HumanInputRequest,
  value: string,
): HumanInputResponse {
  return {
    version: 1,
    kind: "human_input_response",
    source: request.source,
    request_id: request.request_id,
    response_kind: "text",
    value,
  };
}

/** 构建用于普通人类消息内容的人工输入响应文本。 */
export function buildHumanInputResponseText(
  request: HumanInputRequest,
  response: HumanInputResponse,
) {
  return `For your clarification "${request.question}", my answer is: ${response.value}`;
}
