/** 技能列表接口返回的技能描述与启用状态。 */
export interface Skill {
  name: string;
  description: string;
  category: string;
  license: string;
  enabled: boolean;
  editable: boolean;
}
