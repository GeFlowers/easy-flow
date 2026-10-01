'''校验计划任务时区和表达式，并计算一次性或定时任务的下一次运行时间。'''

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


def validate_timezone(timezone_name: str) -> str:
    '''确认时区数据库中存在指定名称的时区，未知名称转换为明确的配置错误。'''
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {timezone_name}") from exc
    return timezone_name


def normalize_cron_expression(expr: str) -> str:
    '''校验定时表达式恰有五个字段，并压缩字段间多余空白。'''
    parts = [part for part in expr.split() if part]
    if len(parts) != 5:
        raise ValueError("Cron expression must contain exactly 5 fields")
    return " ".join(parts)


def next_run_at(
    schedule_type: str,
    schedule_spec: dict[str, object],
    timezone_name: str,
    *,
    now: datetime,
) -> datetime | None:
    '''根据任务类型、计划参数及时区计算未来运行时刻；已过期的一次性计划返回 None。'''
    validate_timezone(timezone_name)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    if schedule_type == "once":
        run_at_raw = schedule_spec.get("run_at")
        if not isinstance(run_at_raw, str):
            raise ValueError("once schedule requires run_at")
        run_at = datetime.fromisoformat(run_at_raw)
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=ZoneInfo(timezone_name))
        return run_at if run_at > now else None

    if schedule_type == "cron":
        cron_expr = normalize_cron_expression(str(schedule_spec.get("cron", "")))
        zone = ZoneInfo(timezone_name)
        local_now = now.astimezone(zone)
        next_local = croniter(cron_expr, local_now).get_next(datetime)
        if next_local.tzinfo is None:
            next_local = next_local.replace(tzinfo=zone)
        return next_local.astimezone(UTC)

    raise ValueError(f"Unsupported schedule_type: {schedule_type}")
