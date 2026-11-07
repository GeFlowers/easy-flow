import type { WorkspaceChangeSummary, WorkspaceFileChange } from "./types";

/** 统一差异中各行对应的渲染样式类别。 */
export type WorkspaceChangeLineClass =
  | "addition"
  | "context"
  | "deletion"
  | "hunk"
  | "meta";

/** 计算摘要中发生变更的文件总数。 */
export function getChangedFileCount(summary: WorkspaceChangeSummary) {
  return summary.created + summary.modified + summary.deleted;
}

/** 生成工作区变更徽标的显示文本。 */
export function getWorkspaceChangeBadgeLabel(summary: WorkspaceChangeSummary) {
  const count = getChangedFileCount(summary);
  return `${count} ${count === 1 ? "file" : "files"} changed +${summary.additions} -${summary.deletions}`;
}

/** 根据统一差异行前缀确定渲染样式类别。 */
export function getWorkspaceChangeLineClass(
  line: string,
): WorkspaceChangeLineClass {
  // 统一差异的文件头必须带尾随空格；仅匹配裸前缀会误将以这些字符开头的真实内容行标为元数据。
  if (line.startsWith("+++ ") || line.startsWith("--- ")) {
    return "meta";
  }
  if (line.startsWith("@@")) {
    return "hunk";
  }
  if (line.startsWith("+")) {
    return "addition";
  }
  if (line.startsWith("-")) {
    return "deletion";
  }
  return "context";
}

/** 按文件状态和路径生成稳定排序的工作区变更副本。 */
export function sortWorkspaceChanges(files: WorkspaceFileChange[]) {
  const statusRank = {
    created: 0,
    modified: 1,
    deleted: 2,
  } satisfies Record<WorkspaceFileChange["status"], number>;

  return [...files].sort((left, right) => {
    const rankDiff = statusRank[left.status] - statusRank[right.status];
    if (rankDiff !== 0) {
      return rankDiff;
    }
    return left.path.localeCompare(right.path);
  });
}
