import { describe, expect, it } from "@rstest/core";

import type { Skill } from "@/core/skills";
import {
  parseSlashSkillReference,
  resolveSlashSkillDisplay,
} from "@/core/skills/slash";

/**
 * 构造测试所需的稳定夹具，使调用处能够明确复用 makeSkill 的约定。

 */

function makeSkill(name: string, enabled = true): Skill {
  return {
    name,
    description: `${name} description`,
    enabled,
  } as Skill;
}

describe("parseSlashSkillReference", () => {
  /**
   * 覆盖“parses a leading /skill and captures the remaining text”这一可观察行为，防止相关边界在重构后回归。
   */
  it("parses a leading /skill and captures the remaining text", () => {
    expect(parseSlashSkillReference("/data-analysis summarize this")).toEqual({
      name: "data-analysis",
      remainingText: "summarize this",
    });
  });

  /**
   * 覆盖“parses a bare /skill with no task text”这一可观察行为，防止相关边界在重构后回归。

   */

  it("parses a bare /skill with no task text", () => {
    expect(parseSlashSkillReference("/data-analysis")).toEqual({
      name: "data-analysis",
      remainingText: "",
    });
  });

  /**
   * 覆盖“ignores reserved control commands”这一可观察行为，防止相关边界在重构后回归。

   */

  it("ignores reserved control commands", () => {
    expect(parseSlashSkillReference("/goal ship it")).toBeNull();
    expect(parseSlashSkillReference("/help")).toBeNull();
  });

  /**
   * 覆盖“returns null when text is not a leading slash command”这一可观察行为，防止相关边界在重构后回归。

   */

  it("returns null when text is not a leading slash command", () => {
    expect(parseSlashSkillReference("hello /data-analysis")).toBeNull();
    expect(parseSlashSkillReference("/a/b")).toBeNull();
    expect(parseSlashSkillReference("plain text")).toBeNull();
  });
});

describe("resolveSlashSkillDisplay", () => {
  const skills = [makeSkill("data-analysis"), makeSkill("frontend-design")];

  /**
   * 覆盖“resolves when the referenced skill exists and is enabled”这一可观察行为，防止相关边界在重构后回归。

   */

  it("resolves when the referenced skill exists and is enabled", () => {
    expect(resolveSlashSkillDisplay("/data-analysis go", skills)).toEqual({
      name: "data-analysis",
      remainingText: "go",
    });
  });

  /**
   * 覆盖“returns null for a slash command that is not an installed skill”这一可观察行为，防止相关边界在重构后回归。

   */

  it("returns null for a slash command that is not an installed skill", () => {
    expect(resolveSlashSkillDisplay("/hello world", skills)).toBeNull();
    expect(resolveSlashSkillDisplay("/unknown-skill do it", skills)).toBeNull();
  });

  /**
   * 覆盖“returns null when the skill exists but is disabled”这一可观察行为，防止相关边界在重构后回归。

   */

  it("returns null when the skill exists but is disabled", () => {
    expect(
      resolveSlashSkillDisplay("/legacy-skill x", [
        makeSkill("legacy-skill", false),
      ]),
    ).toBeNull();
  });
});
