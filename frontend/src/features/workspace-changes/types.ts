/** 工作区文件的变更状态。 */
export type WorkspaceChangeStatus = "created" | "modified" | "deleted";

/** 无法返回文件差异内容的原因。 */
export type DiffUnavailableReason =
  | "binary"
  | "large"
  | "sensitive"
  | "truncated";

/** 工作区文件变更的汇总计数。 */
export interface WorkspaceChangeSummary {
  created: number;
  modified: number;
  deleted: number;
  additions: number;
  deletions: number;
  truncated: boolean;
}

/** 单个工作区文件的变更详情及可选差异内容。 */
export interface WorkspaceFileChange {
  path: string;
  root: string;
  status: WorkspaceChangeStatus;
  binary: boolean;
  sensitive: boolean;
  size_before: number | null;
  size_after: number | null;
  sha256_before: string | null;
  sha256_after: string | null;
  diff: string;
  diff_truncated: boolean;
  diff_unavailable_reason: DiffUnavailableReason | null;
  additions: number;
  deletions: number;
}

/** 工作区变更查询返回的完整数据结构。 */
export interface WorkspaceChangesResponse {
  available: boolean;
  version: number;
  summary: WorkspaceChangeSummary;
  files: WorkspaceFileChange[];
  limits: Record<string, unknown>;
}
