/** 描述一条带来源与可信度的用户记忆事实。 */
export interface MemoryFact {
  id: string;
  content: string;
  category: string;
  confidence: number;
  createdAt: string;
  source: string;
  sourceError?: string | null;
  expected_valid_days?: number | null;
}

/** 创建记忆事实时需要提交的内容、分类和可信度。 */
export interface MemoryFactInput {
  content: string;
  category: string;
  confidence: number;
}

/** 更新记忆事实时可选提交的字段。 */
export interface MemoryFactPatchInput {
  content?: string;
  category?: string;
  confidence?: number;
}

/** 用户上下文与历史背景共用的单段摘要结构。 */
export interface MemorySummary {
  summary: string;
  updatedAt: string;
}

/** 描述用户记忆的版本、两个独立摘要与事实集合。 */
export interface UserMemory {
  version: string;
  lastUpdated: string;
  user: MemorySummary;
  history: MemorySummary;
  facts: MemoryFact[];
}
