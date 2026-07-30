import type { Skill } from "./type";

/**
 * 占用前导斜杠的编辑器控制命令，绝不可显示为技能激活。其取值和名称语法必须镜像后端拦截规则；
 * 前后端的契约测试均固定到共享样例。只在一端新增保留命令或改变名称语法会使持续集成失败。
 */
export const RESERVED_SLASH_SKILL_NAMES = new Set([
  "bootstrap",
  "goal",
  "help",
  "memory",
  "models",
  "new",
  "status",
]);

/** 匹配严格的斜杠技能名称语法；必须与后端共享契约保持一致。 */
export const SLASH_SKILL_RE = /^\/([a-z0-9]+(?:-[a-z0-9]+)*)(?:\s+|$)/;

/** 从文本开头解析出的技能名称及其剩余任务文本。 */
export type SlashSkillReference = {
  name: string;
  remainingText: string;
};

/**
 * 解析严格的“斜杠技能名加任务”语法，并忽略保留控制命令。该规则镜像后端；
 * 文本不是斜杠技能激活时返回空值。
 */
export function parseSlashSkillReference(
  text: string,
): SlashSkillReference | null {
  const match = SLASH_SKILL_RE.exec(text);
  if (!match) {
    return null;
  }
  const name = match[1];
  if (!name || RESERVED_SLASH_SKILL_NAMES.has(name)) {
    return null;
  }
  return {
    name,
    remainingText: text.slice(match[0].length).replace(/^\s+/, ""),
  };
}

/**
 * 按已启用的技能目录解析斜杠技能引用，匹配后端拦截规则：仅已安装且启用的技能可以激活。
 * 文本不是斜杠命令，或技能未知／已禁用时返回空值，使调用方回退为纯文本渲染。
 */
export function resolveSlashSkillDisplay(
  text: string,
  skills: Skill[],
): SlashSkillReference | null {
  const reference = parseSlashSkillReference(text);
  if (!reference) {
    return null;
  }
  const enabled = skills.some(
    (skill) => skill.enabled && skill.name === reference.name,
  );
  return enabled ? reference : null;
}
