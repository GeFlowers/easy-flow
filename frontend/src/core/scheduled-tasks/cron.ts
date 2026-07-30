/**
 * 定时任务表单使用的预设辅助函数。
 *
 * 此处均为无外部依赖的纯函数。预设生成的定时表达式均由本端产生，因此正常流程无需解析任意表达式；
 * 解析函数仅往返处理本端生成的规范形式，其他形式一律回退为自定义预设。
 */

/** 表单支持的定时预设类型；自定义预设保留用户输入的原始表达式。 */
export type CronPreset = "hourly" | "daily" | "weekly" | "monthly" | "custom";

/** 星期的内部标识，按周一至周日排列。 */
export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

/** 构成定时预设表单的可选字段。 */
export type CronParts = {
  minute?: number;
  hour?: number;
  weekdays?: Weekday[];
  dayOfMonth?: number;
  raw?: string;
};

/** 定时任务表单的完整计划状态。 */
export type ScheduleFormState = {
  scheduleType: "once" | "cron";
  preset?: CronPreset;
  parts?: CronParts;
/** 按指定时区解释的本地墙上时间值，格式为“年-月-日时:分”。 */
  runAtLocal?: string;
  timezone: string;
};

/** 生成计划概览时使用的语言。 */
export type ScheduleLocale = "en" | "zh";

/** 供周计划表单和排序使用的标准星期序列。 */
export const WEEKDAYS: Weekday[] = [
  "mon",
  "tue",
  "wed",
  "thu",
  "fri",
  "sat",
  "sun",
];

const WEEKDAY_TO_CRON: Record<Weekday, string> = {
  mon: "1",
  tue: "2",
  wed: "3",
  thu: "4",
  fri: "5",
  sat: "6",
  sun: "0",
};

const CRON_TO_WEEKDAY: Record<string, Weekday> = {
  "0": "sun",
  "1": "mon",
  "2": "tue",
  "3": "wed",
  "4": "thu",
  "5": "fri",
  "6": "sat",
  "7": "sun",
};

const EN_WEEKDAY: Record<Weekday, string> = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};

const ZH_WEEKDAY: Record<Weekday, string> = {
  mon: "周一",
  tue: "周二",
  wed: "周三",
  thu: "周四",
  fri: "周五",
  sat: "周六",
  sun: "周日",
};

/** 将数值限制在给定的闭区间内。 */
function clamp(
  value: number | undefined,
  min: number,
  max: number,
  fallback: number,
): number {
  const n =
    typeof value === "number" && Number.isFinite(value) ? value : fallback;
  return Math.max(min, Math.min(max, Math.trunc(n)));
}

/** 将有限数值截断后补齐为两位字符串，非法值按 0 处理。 */
export function pad2(n: number): string {
  return String(Math.trunc(Number.isFinite(n) ? n : 0)).padStart(2, "0");
}

/** 按定时表达式约定的周日到周六顺序整理星期集合。 */
function orderedWeekdays(days: Weekday[] | undefined): Weekday[] {
  const set = new Set(days ?? []);
  return WEEKDAYS.filter((w) => set.has(w));
}

/** 根据预设与表单字段生成五段定时表达式。 */
export function serializeCron(preset: CronPreset, parts: CronParts): string {
  const m = clamp(parts.minute, 0, 59, 0);
  const h = clamp(parts.hour, 0, 23, 9);
  switch (preset) {
    case "hourly":
      return `${m} * * * *`;
    case "daily":
      return `${m} ${h} * * *`;
    case "weekly": {
      const ordered = orderedWeekdays(parts.weekdays);
      if (ordered.length === 0) {
        return `${m} ${h} * * *`;
      }
      const dow = ordered.map((w) => WEEKDAY_TO_CRON[w]).join(",");
      return `${m} ${h} * * ${dow}`;
    }
    case "monthly": {
      const dom = clamp(parts.dayOfMonth, 1, 31, 1);
      return `${m} ${h} ${dom} * *`;
    }
    case "custom":
      return (parts.raw ?? "").trim() || "0 9 * * *";
  }
  // 不可达：上方分支已穷尽全部预设取值。
  return (parts.raw ?? "").trim() || "0 9 * * *";
}

/** 判断定时表达式字段是否为通配符。 */
function isStar(field: string): boolean {
  return field === "*";
}

/** 判断星期字段是否为可直接解析的逗号分隔数字列表。 */
function isSimpleDowList(field: string): boolean {
  return field.split(",").every((tok) => /^[0-7]$/.test(tok));
}

/** 将支持的五段定时表达式解析为界面预设与字段值。 */
export function parseCron(cron: string): {
  preset: CronPreset;
  parts: CronParts;
} {
  const expr = cron.trim();
  const fields = expr.split(/\s+/);
  if (fields.length !== 5) {
    return { preset: "custom", parts: { raw: expr } };
  }
  // 上方已验证字段数量为五，因此各索引均有定义。
  const mF = fields[0]!;
  const hF = fields[1]!;
  const domF = fields[2]!;
  const monF = fields[3]!;
  const dowF = fields[4]!;
  const numMinute = /^\d+$/.test(mF);
  const numHour = /^\d+$/.test(hF);
  const numDom = /^\d+$/.test(domF);
  const stars = isStar(domF) && isStar(monF);

  if (numMinute && isStar(hF) && stars && isStar(dowF)) {
    return { preset: "hourly", parts: { minute: Number(mF) } };
  }
  if (numMinute && numHour && stars && isStar(dowF)) {
    return {
      preset: "daily",
      parts: { minute: Number(mF), hour: Number(hF) },
    };
  }
  if (
    numMinute &&
    numHour &&
    isStar(domF) &&
    isStar(monF) &&
    !isStar(dowF) &&
    isSimpleDowList(dowF)
  ) {
    const parsed = dowF
      .split(",")
      .map((tok) => CRON_TO_WEEKDAY[tok])
      .filter((w): w is Weekday => Boolean(w));
    const ordered = orderedWeekdays(parsed);
    if (ordered.length > 0) {
      return {
        preset: "weekly",
        parts: { minute: Number(mF), hour: Number(hF), weekdays: ordered },
      };
    }
  }
  if (numMinute && numHour && numDom && isStar(monF) && isStar(dowF)) {
    return {
      preset: "monthly",
      parts: { minute: Number(mF), hour: Number(hF), dayOfMonth: Number(domF) },
    };
  }
  return { preset: "custom", parts: { raw: expr } };
}

/** 生成定时任务计划的本地化概览文本。 */
export function describeSchedule(
  state: ScheduleFormState,
  locale: ScheduleLocale,
): string {
  const tz = state.timezone;
  const zh = locale === "zh";

  if (state.scheduleType === "once") {
    const runAt = (state.runAtLocal ?? "").replace("T", " ");
    return zh ? `单次 ${runAt} (${tz})` : `Once at ${runAt} (${tz})`;
  }

  const parts = state.parts ?? {};
  const hhmm = `${pad2(parts.hour ?? 0)}:${pad2(parts.minute ?? 0)}`;

  switch (state.preset) {
    case "hourly": {
      const minute = parts.minute ?? 0;
      return zh
        ? `每小时第 ${minute} 分钟 (${tz})`
        : `Every hour at :${pad2(minute)} (${tz})`;
    }
    case "daily":
      return zh ? `每天 ${hhmm} (${tz})` : `Every day at ${hhmm} (${tz})`;
    case "weekly": {
      const ordered = orderedWeekdays(parts.weekdays);
      if (ordered.length === 0) {
        return zh ? `每天 ${hhmm} (${tz})` : `Every day at ${hhmm} (${tz})`;
      }
      if (zh) {
        const names = ordered.map((w) => ZH_WEEKDAY[w]).join("、");
        return `每周 ${names} ${hhmm} (${tz})`;
      }
      const names = ordered.map((w) => EN_WEEKDAY[w]).join(", ");
      return `Every ${names} at ${hhmm} (${tz})`;
    }
    case "monthly": {
      const dom = parts.dayOfMonth ?? 1;
      return zh
        ? `每月 ${dom} 日 ${hhmm} (${tz})`
        : `On day ${dom} of every month at ${hhmm} (${tz})`;
    }
    case "custom":
      return zh
        ? `自定义: ${parts.raw ?? ""} (${tz})`
        : `Custom: ${parts.raw ?? ""} (${tz})`;
  }
  // 不可达：上方分支已穷尽全部预设取值。
  return zh ? `自定义 (${tz})` : `Custom (${tz})`;
}

/**
 * 将指定时区的本地墙上时间转换为带显式协调世界时偏移的标准时间字符串。
 *
 * 后端会把无时区时间当作协调世界时；因此通过国际化时间接口推导偏移，并在夏令时切换附近再次校正，
 * 保证正反转换的往返结果一致。
 */
export function zonedLocalToUtcIso(
  localValue: string,
  timezone: string,
): string {
  const [date, time] = localValue.split("T");
  const [y, mo, d] = (date ?? "").split("-").map(Number);
  const [h, mi] = (time ?? "00:00").split(":").map(Number);
  const refMs = Date.UTC(y ?? 1970, (mo ?? 1) - 1, d ?? 1, h ?? 0, mi ?? 0);
  // 若墙上时间按协调世界时解释的时刻与真实时刻之间发生夏令时切换，该时刻的偏移会失效：例如春季跳时
  // 当天的“03:30”会使用切换前偏移，导致延后一小时触发，并破坏正反转换的往返。
  // 先解析一次，再在候选时刻重新推导偏移；真实时区经一次修正即可收敛。
  let offsetMs = tzOffsetMs(timezone, new Date(refMs));
  let utcMs = refMs - offsetMs;
  const correctedOffsetMs = tzOffsetMs(timezone, new Date(utcMs));
  if (correctedOffsetMs !== offsetMs) {
    offsetMs = correctedOffsetMs;
    utcMs = refMs - offsetMs;
  }
  const utc = new Date(utcMs);
  return `${utc.getUTCFullYear()}-${pad2(utc.getUTCMonth() + 1)}-${pad2(
    utc.getUTCDate(),
  )}T${pad2(utc.getUTCHours())}:${pad2(utc.getUTCMinutes())}:${pad2(
    utc.getUTCSeconds(),
  )}+00:00`;
}

/**
 * 将已保存的协调世界时标准时间按指定时区渲染为本地表单值，用于编辑单次任务。
 * 这是本地时间转协调世界时函数的逆操作。
 */
export function utcToZonedLocalInput(iso: string, timezone: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return "";
  }
  const offsetMs = tzOffsetMs(timezone, d);
  const local = new Date(d.getTime() + offsetMs);
  return `${local.getUTCFullYear()}-${pad2(local.getUTCMonth() + 1)}-${pad2(
    local.getUTCDate(),
  )}T${pad2(local.getUTCHours())}:${pad2(local.getUTCMinutes())}`;
}

/** 计算某时区在指定时刻相对协调世界时的毫秒偏移。 */
function tzOffsetMs(timezone: string, date: Date): number {
  const tzParts = formatParts(timezone, date);
  const utcParts = formatParts("UTC", date);
  const tzMs = toUtcMs(tzParts);
  const utcMs = toUtcMs(utcParts);
  // 大于零表示该时区的墙上时钟领先协调世界时（位于其以东）。
  return tzMs - utcMs;
}

/** 提取日期在指定时区的数值组成部分。 */
function formatParts(timezone: string, date: Date): Record<string, number> {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(date);
  const out: Record<string, number> = {};
  for (const p of parts) {
    out[p.type] = Number(p.value);
  }
  return out;
}

/** 将日期组成部分按协调世界时解释并转换为毫秒时间戳。 */
function toUtcMs(p: Record<string, number>): number {
  return Date.UTC(
    p.year ?? 1970,
    (p.month ?? 1) - 1,
    p.day ?? 1,
    p.hour ?? 0,
    p.minute ?? 0,
    p.second ?? 0,
  );
}
