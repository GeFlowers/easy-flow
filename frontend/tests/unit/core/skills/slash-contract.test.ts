import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "@rstest/core";

import {
  RESERVED_SLASH_SKILL_NAMES,
  SLASH_SKILL_RE,
} from "@/core/skills/slash";

interface ContractFile {
  reserved_slash_skill_names: string[];
  skill_name_pattern: string;
}

const CONTRACT_PATH = resolve(
  __dirname,
  "../../../../../contracts/slash_skill_contract.json",
);
const CONTRACT: ContractFile = JSON.parse(
  readFileSync(CONTRACT_PATH, "utf-8"),
) as ContractFile;

describe("slash-skill contract", () => {
  /**
   * 覆盖“reserved names match the shared contract fixture”这一可观察行为，防止相关边界在重构后回归。
   */
  it("reserved names match the shared contract fixture", () => {
    expect([...RESERVED_SLASH_SKILL_NAMES].sort()).toEqual(
      [...CONTRACT.reserved_slash_skill_names].sort(),
    );
  });

  /**
   * 覆盖“skill-name grammar matches the shared contract fixture”这一可观察行为，防止相关边界在重构后回归。

   */

  it("skill-name grammar matches the shared contract fixture", () => {
    // 契约存储 Python 规范形式的模式（未转义的 `/`）。通过 RegExp 构造函数将两者
    // 规范化，避免比较被 JS 在 `.source` 中将分隔符转义为 `\/` 干扰。
    expect(SLASH_SKILL_RE.source).toBe(
      new RegExp(CONTRACT.skill_name_pattern).source,
    );
  });
});
