import { describe, expect, test } from "@rstest/core";

import {
  describeSchedule,
  parseCron,
  serializeCron,
  utcToZonedLocalInput,
  zonedLocalToUtcIso,
  type CronParts,
} from "@/core/scheduled-tasks/cron";

describe("serializeCron", () => {
  /**
   * 覆盖“hourly emits minute + star fields”这一可观察行为，防止相关边界在重构后回归。
   */
  test("hourly emits minute + star fields", () => {
    expect(serializeCron("hourly", { minute: 30 } as CronParts)).toBe(
      "30 * * * *",
    );
  });

  /**
   * 覆盖“daily emits minute + hour”这一可观察行为，防止相关边界在重构后回归。

   */

  test("daily emits minute + hour", () => {
    expect(serializeCron("daily", { minute: 0, hour: 9 } as CronParts)).toBe(
      "0 9 * * *",
    );
  });

  /**
   * 覆盖“weekly emits comma-joined weekday numbers in cron order (0=sun)”这一可观察行为，防止相关边界在重构后回归。

   */

  test("weekly emits comma-joined weekday numbers in cron order (0=sun)", () => {
    expect(
      serializeCron("weekly", {
        minute: 0,
        hour: 9,
        weekdays: ["mon", "wed"],
      } as CronParts),
    ).toBe("0 9 * * 1,3");
  });

  /**
   * 覆盖“weekly sorts + dedupes out-of-order / duplicate weekdays”这一可观察行为，防止相关边界在重构后回归。

   */

  test("weekly sorts + dedupes out-of-order / duplicate weekdays", () => {
    expect(
      serializeCron("weekly", {
        minute: 0,
        hour: 9,
        weekdays: ["wed", "mon", "wed"],
      } as CronParts),
    ).toBe("0 9 * * 1,3");
  });

  /**
   * 覆盖“weekly maps sunday to 0”这一可观察行为，防止相关边界在重构后回归。

   */

  test("weekly maps sunday to 0", () => {
    expect(
      serializeCron("weekly", {
        minute: 0,
        hour: 9,
        weekdays: ["sun"],
      } as CronParts),
    ).toBe("0 9 * * 0");
  });

  /**
   * 覆盖“monthly emits day-of-month”这一可观察行为，防止相关边界在重构后回归。

   */

  test("monthly emits day-of-month", () => {
    expect(
      serializeCron("monthly", {
        minute: 0,
        hour: 9,
        dayOfMonth: 1,
      } as CronParts),
    ).toBe("0 9 1 * *");
  });

  /**
   * 覆盖“custom returns raw expression”这一可观察行为，防止相关边界在重构后回归。

   */

  test("custom returns raw expression", () => {
    expect(serializeCron("custom", { raw: "*/5 * * * *" } as CronParts)).toBe(
      "*/5 * * * *",
    );
  });

  /**
   * 覆盖“clamps out-of-range minute / hour / day-of-month”这一可观察行为，防止相关边界在重构后回归。

   */

  test("clamps out-of-range minute / hour / day-of-month", () => {
    expect(serializeCron("daily", { minute: 99, hour: 24 } as CronParts)).toBe(
      "59 23 * * *",
    );
    expect(
      serializeCron("monthly", {
        minute: 0,
        hour: 9,
        dayOfMonth: 32,
      } as CronParts),
    ).toBe("0 9 31 * *");
    expect(
      serializeCron("monthly", {
        minute: 0,
        hour: 9,
        dayOfMonth: 0,
      } as CronParts),
    ).toBe("0 9 1 * *");
  });
});

describe("parseCron", () => {
  /**
   * 覆盖“hourly: M * * * *”这一可观察行为，防止相关边界在重构后回归。
   */
  test("hourly: M * * * *", () => {
    expect(parseCron("30 * * * *").preset).toBe("hourly");
    expect(parseCron("30 * * * *").parts.minute).toBe(30);
  });

  /**
   * 覆盖“daily: M H * * *”这一可观察行为，防止相关边界在重构后回归。

   */

  test("daily: M H * * *", () => {
    const r = parseCron("0 9 * * *");
    expect(r.preset).toBe("daily");
    expect(r.parts).toMatchObject({ minute: 0, hour: 9 });
  });

  /**
   * 覆盖“weekly: M H * * DOW”这一可观察行为，防止相关边界在重构后回归。

   */

  test("weekly: M H * * DOW", () => {
    const r = parseCron("0 9 * * 1,3");
    expect(r.preset).toBe("weekly");
    expect(r.parts.weekdays).toEqual(["mon", "wed"]);
  });

  /**
   * 覆盖“weekly maps 0 and 7 to sunday”这一可观察行为，防止相关边界在重构后回归。

   */

  test("weekly maps 0 and 7 to sunday", () => {
    expect(parseCron("0 9 * * 0").parts.weekdays).toEqual(["sun"]);
    expect(parseCron("0 9 * * 7").parts.weekdays).toEqual(["sun"]);
  });

  /**
   * 覆盖“monthly: M H DOM * *”这一可观察行为，防止相关边界在重构后回归。

   */

  test("monthly: M H DOM * *", () => {
    const r = parseCron("0 9 1 * *");
    expect(r.preset).toBe("monthly");
    expect(r.parts.dayOfMonth).toBe(1);
  });

  /**
   * 覆盖“non-canonical forms fall back to custom”这一可观察行为，防止相关边界在重构后回归。

   */

  test("non-canonical forms fall back to custom", () => {
    expect(parseCron("*/5 * * * *").preset).toBe("custom");
    expect(parseCron("0 9,10 * * *").preset).toBe("custom");
    expect(parseCron("0 9 * * 1-5").preset).toBe("custom");
    expect(parseCron("garbage").preset).toBe("custom");
    expect(parseCron("garbage").parts.raw).toBe("garbage");
  });
});

describe("describeSchedule", () => {
  const baseCron = {
    minute: 0,
    hour: 9,
    weekdays: [],
    dayOfMonth: 1,
  } as CronParts;

  /**
   * 覆盖“once renders wall time + timezone (en)”这一可观察行为，防止相关边界在重构后回归。

   */

  test("once renders wall time + timezone (en)", () => {
    expect(
      describeSchedule(
        {
          scheduleType: "once",
          runAtLocal: "2026-07-02T09:00",
          timezone: "Asia/Shanghai",
        },
        "en",
      ),
    ).toBe("Once at 2026-07-02 09:00 (Asia/Shanghai)");
  });

  /**
   * 覆盖“daily en”这一可观察行为，防止相关边界在重构后回归。

   */

  test("daily en", () => {
    expect(
      describeSchedule(
        {
          scheduleType: "cron",
          preset: "daily",
          parts: baseCron,
          timezone: "UTC",
        },
        "en",
      ),
    ).toBe("Every day at 09:00 (UTC)");
  });

  /**
   * 覆盖“daily zh”这一可观察行为，防止相关边界在重构后回归。

   */

  test("daily zh", () => {
    expect(
      describeSchedule(
        {
          scheduleType: "cron",
          preset: "daily",
          parts: baseCron,
          timezone: "UTC",
        },
        "zh",
      ),
    ).toBe("每天 09:00 (UTC)");
  });

  /**
   * 覆盖“weekly en lists weekday abbreviations”这一可观察行为，防止相关边界在重构后回归。

   */

  test("weekly en lists weekday abbreviations", () => {
    expect(
      describeSchedule(
        {
          scheduleType: "cron",
          preset: "weekly",
          parts: { ...baseCron, weekdays: ["mon", "wed"] },
          timezone: "UTC",
        },
        "en",
      ),
    ).toBe("Every Mon, Wed at 09:00 (UTC)");
  });

  /**
   * 覆盖“weekly zh lists 周X”这一可观察行为，防止相关边界在重构后回归。

   */

  test("weekly zh lists 周X", () => {
    expect(
      describeSchedule(
        {
          scheduleType: "cron",
          preset: "weekly",
          parts: { ...baseCron, weekdays: ["mon", "wed", "fri"] },
          timezone: "UTC",
        },
        "zh",
      ),
    ).toBe("每周 周一、周三、周五 09:00 (UTC)");
  });

  /**
   * 覆盖“weekly with no weekdays falls back to daily wording”这一可观察行为，防止相关边界在重构后回归。

   */

  test("weekly with no weekdays falls back to daily wording", () => {
    expect(
      describeSchedule(
        {
          scheduleType: "cron",
          preset: "weekly",
          parts: { ...baseCron, weekdays: [] },
          timezone: "UTC",
        },
        "en",
      ),
    ).toBe("Every day at 09:00 (UTC)");
  });

  /**
   * 覆盖“hourly en”这一可观察行为，防止相关边界在重构后回归。

   */

  test("hourly en", () => {
    expect(
      describeSchedule(
        {
          scheduleType: "cron",
          preset: "hourly",
          parts: { minute: 30 },
          timezone: "UTC",
        },
        "en",
      ),
    ).toBe("Every hour at :30 (UTC)");
  });

  /**
   * 覆盖“monthly en”这一可观察行为，防止相关边界在重构后回归。

   */

  test("monthly en", () => {
    expect(
      describeSchedule(
        {
          scheduleType: "cron",
          preset: "monthly",
          parts: { minute: 0, hour: 9, dayOfMonth: 1 },
          timezone: "UTC",
        },
        "en",
      ),
    ).toBe("On day 1 of every month at 09:00 (UTC)");
  });

  /**
   * 覆盖“custom en echoes the expression”这一可观察行为，防止相关边界在重构后回归。

   */

  test("custom en echoes the expression", () => {
    expect(
      describeSchedule(
        {
          scheduleType: "cron",
          preset: "custom",
          parts: { raw: "*/5 * * * *" },
          timezone: "UTC",
        },
        "en",
      ),
    ).toBe("Custom: */5 * * * * (UTC)");
  });
});

describe("zonedLocalToUtcIso", () => {
  /**
   * 覆盖“Asia/Shanghai is UTC-8 (wall 09:00 -> 01:00Z)”这一可观察行为，防止相关边界在重构后回归。
   */
  test("Asia/Shanghai is UTC-8 (wall 09:00 -> 01:00Z)", () => {
    expect(zonedLocalToUtcIso("2026-07-02T09:00", "Asia/Shanghai")).toBe(
      "2026-07-02T01:00:00+00:00",
    );
  });

  /**
   * 覆盖“UTC passes through”这一可观察行为，防止相关边界在重构后回归。

   */

  test("UTC passes through", () => {
    expect(zonedLocalToUtcIso("2026-07-02T09:00", "UTC")).toBe(
      "2026-07-02T09:00:00+00:00",
    );
  });

  /**
   * 覆盖“America/New_York July is EDT (-04:00)”这一可观察行为，防止相关边界在重构后回归。

   */

  test("America/New_York July is EDT (-04:00)", () => {
    expect(zonedLocalToUtcIso("2026-07-02T09:00", "America/New_York")).toBe(
      "2026-07-02T13:00:00+00:00",
    );
  });

  /**
   * 覆盖“America/New_York January is EST (-05:00) — DST season flip”这一可观察行为，防止相关边界在重构后回归。

   */

  test("America/New_York January is EST (-05:00) — DST season flip", () => {
    expect(zonedLocalToUtcIso("2026-01-15T09:00", "America/New_York")).toBe(
      "2026-01-15T14:00:00+00:00",
    );
  });

  /**
   * 覆盖“Asia/Kolkata half-hour offset UTC+5:30”这一可观察行为，防止相关边界在重构后回归。

   */

  test("Asia/Kolkata half-hour offset UTC+5:30", () => {
    expect(zonedLocalToUtcIso("2026-07-02T09:00", "Asia/Kolkata")).toBe(
      "2026-07-02T03:30:00+00:00",
    );
  });
});

describe("utcToZonedLocalInput", () => {
  /**
   * 覆盖“Shanghai +8: 01:00Z -> 09:00 wall”这一可观察行为，防止相关边界在重构后回归。
   */
  test("Shanghai +8: 01:00Z -> 09:00 wall", () => {
    expect(
      utcToZonedLocalInput("2026-07-02T01:00:00+00:00", "Asia/Shanghai"),
    ).toBe("2026-07-02T09:00");
  });

  /**
   * 覆盖“New_York EDT: 13:00Z -> 09:00 wall”这一可观察行为，防止相关边界在重构后回归。

   */

  test("New_York EDT: 13:00Z -> 09:00 wall", () => {
    expect(
      utcToZonedLocalInput("2026-07-02T13:00:00+00:00", "America/New_York"),
    ).toBe("2026-07-02T09:00");
  });

  /**
   * 覆盖“invalid -> empty string”这一可观察行为，防止相关边界在重构后回归。

   */

  test("invalid -> empty string", () => {
    expect(utcToZonedLocalInput("not-a-date", "UTC")).toBe("");
  });

  /**
   * 覆盖“round-trips with zonedLocalToUtcIso”这一可观察行为，防止相关边界在重构后回归。

   */

  test("round-trips with zonedLocalToUtcIso", () => {
    const iso = zonedLocalToUtcIso("2026-07-02T09:00", "Asia/Shanghai");
    expect(utcToZonedLocalInput(iso, "Asia/Shanghai")).toBe("2026-07-02T09:00");
  });
});

describe("zonedLocalToUtcIso DST transitions", () => {
  // 2026 年美国夏令时开始：2026-03-08 时钟从 02:00 跳至 03:00（EST 切换为 EDT）。
  /**
   * 覆盖“New_York wall time after spring-forward uses the post-transition offset”这一可观察行为，防止相关边界在重构后回归。
   */
  test("New_York wall time after spring-forward uses the post-transition offset", () => {
    // 03:30 EDT (-4) 对应 07:30Z；过期的转换前偏移量 (-5) 会得出 08:30Z。
    expect(zonedLocalToUtcIso("2026-03-08T03:30", "America/New_York")).toBe(
      "2026-03-08T07:30:00+00:00",
    );
  });

  /**
   * 覆盖“New_York wall time before spring-forward keeps the EST offset”这一可观察行为，防止相关边界在重构后回归。

   */

  test("New_York wall time before spring-forward keeps the EST offset", () => {
    expect(zonedLocalToUtcIso("2026-03-08T01:30", "America/New_York")).toBe(
      "2026-03-08T06:30:00+00:00",
    );
  });

  // 2026 年美国夏令时结束：2026-11-01 的 01:00—02:00 重复一次（EDT 切换为 EST）。
  /**
   * 覆盖“New_York ambiguous fall-back wall time resolves deterministically”这一可观察行为，防止相关边界在重构后回归。
   */
  test("New_York ambiguous fall-back wall time resolves deterministically", () => {
    expect(zonedLocalToUtcIso("2026-11-01T01:30", "America/New_York")).toBe(
      "2026-11-01T05:30:00+00:00",
    );
  });

  /**
   * 覆盖“create -> edit round-trip survives spring-forward”这一可观察行为，防止相关边界在重构后回归。

   */

  test("create -> edit round-trip survives spring-forward", () => {
    const iso = zonedLocalToUtcIso("2026-03-08T03:30", "America/New_York");
    expect(utcToZonedLocalInput(iso, "America/New_York")).toBe(
      "2026-03-08T03:30",
    );
  });

  /**
   * 覆盖“no-DST timezone is unaffected”这一可观察行为，防止相关边界在重构后回归。

   */

  test("no-DST timezone is unaffected", () => {
    expect(zonedLocalToUtcIso("2026-03-08T03:30", "Asia/Shanghai")).toBe(
      "2026-03-07T19:30:00+00:00",
    );
  });
});
