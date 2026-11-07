import type { MemorySummary, UserMemory } from "./types";

/** 判断导入值是否为对象，拒绝数组和空值。 */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 校验单段摘要，供新格式及旧分区备份共同使用。 */
function isSummary(value: unknown): value is MemorySummary {
  return (
    isRecord(value) &&
    typeof value.summary === "string" &&
    typeof value.updatedAt === "string"
  );
}

/** 合并旧分区文字并去重，同时保留最新更新时间；拒绝不完整的旧备份。 */
function parseSummary(
  value: unknown,
  legacyKeys: string[],
): MemorySummary | null {
  if (!isRecord(value)) return null;
  const hasLegacy = legacyKeys.some((key) => key in value);
  if (
    !isSummary(value) &&
    (!hasLegacy || !legacyKeys.every((key) => isSummary(value[key])))
  )
    return null;
  const entries = [
    ...(isSummary(value) ? [value] : []),
    ...legacyKeys.flatMap((key) => (isSummary(value[key]) ? [value[key]] : [])),
  ];
  const summaries = [
    ...new Set(entries.map((entry) => entry.summary.trim()).filter(Boolean)),
  ];
  const latest = entries.reduce<string>((previous, entry) => {
    const nextTime = Date.parse(entry.updatedAt);
    if (!Number.isFinite(nextTime)) return previous;
    const previousTime = Date.parse(previous);
    return !Number.isFinite(previousTime) || nextTime > previousTime
      ? entry.updatedAt
      : previous;
  }, "");
  return {
    summary: summaries.join("\n\n"),
    updatedAt: latest || (isSummary(value) ? value.updatedAt : ""),
  };
}

/** 校验导入事实的必要字段及复核期限，保留其余原始事实信息。 */
function isFact(value: unknown): value is UserMemory["facts"][number] {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.content === "string" &&
    typeof value.category === "string" &&
    typeof value.confidence === "number" &&
    Number.isFinite(value.confidence) &&
    value.confidence >= 0 &&
    value.confidence <= 1 &&
    typeof value.createdAt === "string" &&
    typeof value.source === "string" &&
    (value.sourceError == null || typeof value.sourceError === "string") &&
    (value.expected_valid_days == null ||
      (typeof value.expected_valid_days === "number" &&
        Number.isInteger(value.expected_valid_days) &&
        value.expected_valid_days > 0))
  );
}

/** 将新旧备份统一转换为两个单段摘要；格式错误时不允许覆盖现有记忆。 */
export function parseMemoryImport(value: unknown): UserMemory | null {
  if (
    !isRecord(value) ||
    typeof value.version !== "string" ||
    typeof value.lastUpdated !== "string" ||
    !Array.isArray(value.facts) ||
    !value.facts.every(isFact)
  )
    return null;
  const user = parseSummary(value.user, [
    "workContext",
    "personalContext",
    "topOfMind",
  ]);
  const history = parseSummary(value.history, [
    "recentMonths",
    "earlierContext",
    "longTermBackground",
  ]);
  if (!user || !history) return null;
  return {
    version: "2.0",
    lastUpdated: value.lastUpdated,
    user,
    history,
    facts: value.facts,
  };
}
