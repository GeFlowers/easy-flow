import type { ScheduleValue } from "@/components/workspace/scheduled-task-schedule-input";

/** 定时任务预设标题对应的本地化键。 */
export type RecipeTitleKey = "trending" | "news" | "issues" | "weekly";

/** 可一键套用到定时任务表单的前端预设。 */
export type Recipe = {
  id: string;
  icon: string;
  titleKey: RecipeTitleKey;
  prompt: string;
  schedule: ScheduleValue;
};

/**
 * 仅供前端使用的起始预设。计划时区留空，应用时由计划输入组件回退到浏览器检测的时区；
 * 仓库占位符有意保留，用户套用后会在提示词字段中填写。
 */
export const RECIPES: Recipe[] = [
  {
    id: "trending",
    icon: "🔥",
    titleKey: "trending",
    prompt:
      "使用 web_search 打开今天的 GitHub Trending 页面，总结排名前 10 的仓库。每项列出名称、主要语言、今天新增的星标数，并用一句话说明项目用途和上榜原因。以 Markdown 列表输出。",
    schedule: {
      schedule_type: "cron",
      schedule_spec: { cron: "0 9 * * *" },
      timezone: "",
    },
  },
  {
    id: "news",
    icon: "📰",
    titleKey: "news",
    prompt:
      "使用 web_search 收集今天人工智能、开发工具、基础设施和安全领域的重要科技新闻。总结最重要的 5 条，每条给出标题、来源和一句话要点。以 Markdown 列表输出。",
    schedule: {
      schedule_type: "cron",
      schedule_spec: { cron: "0 9 * * *" },
      timezone: "",
    },
  },
  {
    id: "issues",
    icon: "🏷️",
    titleKey: "issues",
    prompt:
      "整理 {{repo}} 中尚未关闭的问题：列出最近的 10 条，将每条标记为缺陷、功能建议或提问；指出久未更新或优先级较高的条目，并推荐 2 条适合新贡献者处理的问题。将 {{repo}} 替换为目标仓库（所有者/名称）。以 Markdown 表格输出。",
    schedule: {
      schedule_type: "cron",
      schedule_spec: { cron: "0 9 * * *" },
      timezone: "",
    },
  },
  {
    id: "weekly",
    icon: "📅",
    titleKey: "weekly",
    prompt:
      "撰写一份简明的周报，说明本周完成的工作、当前阻碍，以及下周最重要的 3 项任务。",
    schedule: {
      schedule_type: "cron",
      schedule_spec: { cron: "0 9 * * 1" },
      timezone: "",
    },
  },
];
