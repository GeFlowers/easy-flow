import { describe, expect, test } from "@rstest/core";

import {
  getChangedFileCount,
  getWorkspaceChangeBadgeLabel,
  getWorkspaceChangeLineClass,
} from "@/core/workspace-changes/summary";
import type { WorkspaceChangesResponse } from "@/core/workspace-changes/types";

const changes: WorkspaceChangesResponse = {
  available: true,
  version: 1,
  summary: {
    created: 1,
    modified: 2,
    deleted: 0,
    additions: 12,
    deletions: 3,
    truncated: false,
  },
  files: [],
  limits: {},
};

describe("workspace change summary helpers", () => {
  /**
   * 覆盖“counts created, modified, and deleted files”这一可观察行为，防止相关边界在重构后回归。
   */
  test("counts created, modified, and deleted files", () => {
    expect(getChangedFileCount(changes.summary)).toBe(3);
  });

  /**
   * 覆盖“formats the compact badge label”这一可观察行为，防止相关边界在重构后回归。

   */

  test("formats the compact badge label", () => {
    expect(getWorkspaceChangeBadgeLabel(changes.summary)).toBe(
      "3 files changed +12 -3",
    );
  });

  /**
   * 覆盖“classifies unified diff lines”这一可观察行为，防止相关边界在重构后回归。

   */

  test("classifies unified diff lines", () => {
    expect(getWorkspaceChangeLineClass("+new line")).toBe("addition");
    expect(getWorkspaceChangeLineClass("-old line")).toBe("deletion");
    expect(getWorkspaceChangeLineClass("@@ -1 +1 @@")).toBe("hunk");
    expect(getWorkspaceChangeLineClass(" unchanged")).toBe("context");
    expect(getWorkspaceChangeLineClass("+++ b/file.md")).toBe("meta");
    expect(getWorkspaceChangeLineClass("--- a/file.md")).toBe("meta");
  });

  /**
   * 覆盖“treats content lines beginning with +++/--- as add/remove, not meta”这一可观察行为，防止相关边界在重构后回归。

   */

  test("treats content lines beginning with +++/--- as add/remove, not meta", () => {
    expect(getWorkspaceChangeLineClass("+++foo")).toBe("addition");
    expect(getWorkspaceChangeLineClass("---bar")).toBe("deletion");
  });
});
