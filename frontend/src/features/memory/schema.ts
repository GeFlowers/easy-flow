import type { MemorySummary, UserMemory } from "./types";

/** 判断导入值是否为对象，拒绝数组和空值。 */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 校验单段摘要。 */
function isSummary(value: unknown): value is MemorySummary {
  return (
    isRecord(value) &&
    typeof value.summary === "string" &&
    typeof value.updatedAt === "string"
  );
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

/** 校验当前格式的记忆备份；格式错误时不允许覆盖现有记忆。 */
export function parseMemoryImport(value: unknown): UserMemory | null {
  if (
    !isRecord(value) ||
    typeof value.version !== "string" ||
    typeof value.lastUpdated !== "string" ||
    !Array.isArray(value.facts) ||
    !value.facts.every(isFact)
  )
    return null;
  if (!isSummary(value.user) || !isSummary(value.history)) return null;
  const user = value.user;
  const history = value.history;
  return {
    version: "2.0",
    lastUpdated: value.lastUpdated,
    user,
    history,
    facts: value.facts,
  };
}
