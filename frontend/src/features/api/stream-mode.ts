const SUPPORTED_RUN_STREAM_MODES = new Set([
  "values",
  "messages",
  "messages-tuple",
  "updates",
  "events",
  "debug",
  "tasks",
  "checkpoints",
  "custom",
] as const);

const warnedUnsupportedStreamModes = new Set<string>();

/** 每种不支持的 LangGraph 流模式仅警告一次，避免重复日志。 */
export function warnUnsupportedStreamModes(
  modes: string[],
  warn: (message: string) => void = console.warn,
) {
  const unseenModes = modes.filter((mode) => {
    if (warnedUnsupportedStreamModes.has(mode)) {
      return false;
    }
    warnedUnsupportedStreamModes.add(mode);
    return true;
  });

  if (unseenModes.length === 0) {
    return;
  }

  warn(
    `[deer-flow] Dropped unsupported LangGraph stream mode(s): ${unseenModes.join(", ")}`,
  );
}

/** 从运行选项中移除客户端不支持的流模式，并保留其余选项。 */
export function sanitizeRunStreamOptions<T>(options: T): T {
  if (
    typeof options !== "object" ||
    options === null ||
    !("streamMode" in options)
  ) {
    return options;
  }

  const streamMode = options.streamMode;
  if (streamMode == null) {
    return options;
  }

  const requestedModes = Array.isArray(streamMode) ? streamMode : [streamMode];
  const sanitizedModes = requestedModes.filter((mode) =>
    SUPPORTED_RUN_STREAM_MODES.has(mode),
  );

  if (sanitizedModes.length === requestedModes.length) {
    return options;
  }

  const droppedModes = requestedModes.filter(
    (mode) => !SUPPORTED_RUN_STREAM_MODES.has(mode),
  );
  warnUnsupportedStreamModes(droppedModes);

  return {
    ...options,
    streamMode: Array.isArray(streamMode) ? sanitizedModes : sanitizedModes[0],
  };
}
