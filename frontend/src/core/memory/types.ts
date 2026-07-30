/** 描述一条带来源与可信度的用户记忆事实。 */
export interface MemoryFact {
  id: string;
  content: string;
  category: string;
  confidence: number;
  createdAt: string;
  source: string;
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

/** 描述用户记忆的版本、摘要分区与事实集合。 */
export interface UserMemory {
  version: string;
  lastUpdated: string;
  user: {
    workContext: {
      summary: string;
      updatedAt: string;
    };
    personalContext: {
      summary: string;
      updatedAt: string;
    };
    topOfMind: {
      summary: string;
      updatedAt: string;
    };
  };
  history: {
    recentMonths: {
      summary: string;
      updatedAt: string;
    };
    earlierContext: {
      summary: string;
      updatedAt: string;
    };
    longTermBackground: {
      summary: string;
      updatedAt: string;
    };
  };
  facts: MemoryFact[];
}
