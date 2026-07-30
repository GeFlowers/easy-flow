import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { Skill } from "./type";

/** 技能接口请求失败时携带响应状态的错误类型。 */
export class SkillRequestError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "SkillRequestError";
    this.status = status;
  }

  get isAdminRequired(): boolean {
    return this.status === 403;
  }
}

/** 从失败响应中读取技能接口可展示的错误详情。 */
async function readErrorDetail(response: Response): Promise<string> {
  const data = (await response.json().catch(() => ({}))) as {
    detail?: string;
  };
  return data.detail ?? `HTTP ${response.status}: ${response.statusText}`;
}

/** 加载当前可用技能及其启用状态。 */
export async function loadSkills() {
  const skills = await fetch(`${getBackendBaseURL()}/api/skills`);
  if (!skills.ok) {
    throw new SkillRequestError(skills.status, await readErrorDetail(skills));
  }
  const json = await skills.json();
  return json.skills as Skill[];
}

/** 更新指定技能的启用状态。 */
export async function enableSkill(skillName: string, enabled: boolean) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/skills/${skillName}`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        enabled,
      }),
    },
  );
  if (!response.ok) {
    throw new SkillRequestError(
      response.status,
      await readErrorDetail(response),
    );
  }
  return response.json();
}

/** 安装技能包时提交给后端的来源与所属线程。 */
export interface InstallSkillRequest {
  thread_id: string;
  path: string;
}

/** 后端返回的技能安装结果；非授权类响应错误会以软失败形式返回。 */
export interface InstallSkillResponse {
  success: boolean;
  skill_name: string;
  message: string;
}

/** 安装技能包，并将来源与配置提交给后端。 */
export async function installSkill(
  request: InstallSkillRequest,
): Promise<InstallSkillResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/skills/install`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const message = await readErrorDetail(response);
    // 暴露授权失败，让调用方展示仅管理员可用的提示而非通用失败信息。
    if (response.status === 403) {
      throw new SkillRequestError(response.status, message);
    }
    // 其他响应错误维持既有的软失败约定。
    return {
      success: false,
      skill_name: "",
      message,
    };
  }

  return response.json();
}
