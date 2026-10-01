'''只读运维控制台端点。

汇总当前用户全部线程的可观测性数据，包括运行历史、时间范围内的 Token 支出和资产
计数，可作为运维仪表盘或外部监控消费者的数据层。

该模块仅负责报表，不参与运行时执行：它对 harness 管理的 ``runs`` / ``threads_meta``
表执行短生命周期的只读查询，而不扩展运行时 `RunStore` 的接口。报表查询使用 PostgreSQL。
'''

import asyncio
import logging
from datetime import UTC, datetime, time, timedelta
from typing import NamedTuple

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.gateway.authz import require_permission
from app.gateway.deps import get_current_user
from deerflow.config import get_app_config
from deerflow.config.agents_config import list_custom_agents
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/console", tags=["console"])

_ACTIVE_STATUSES = ("pending", "running")
_FAILED_STATUSES = ("error", "timeout")

# 限制列表响应中的错误摘要长度；完整文本保留在运行记录中。
_ERROR_EXCERPT_CHARS = 300


# 响应模型


class ConsoleStatsResponse(BaseModel):
    '''控制台仪表盘的核心统计计数。'''

    total_runs: int = Field(..., description="All recorded runs for the current user")
    active_runs: int = Field(..., description="Runs currently pending or running")
    failed_runs: int = Field(..., description="Runs that ended in error or timeout")
    total_threads: int = Field(..., description="Conversation threads owned by the current user")
    total_agents: int = Field(..., description="Custom agents owned by the current user")
    total_tokens: int = Field(..., description="Tokens consumed across all recorded runs")
    total_cost: float | None = Field(default=None, description="Estimated spend across priced runs; null when no models[*].pricing is configured")
    currency: str | None = Field(default=None, description="Display currency taken from the first configured pricing entry")


class ConsoleRunItem(BaseModel):
    '''跨线程运行列表中的一次运行。'''

    run_id: str
    thread_id: str
    thread_title: str | None = Field(default=None, description="Display name from threads_meta, if tracked")
    assistant_id: str | None = None
    status: str
    model_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, description="Wall-clock duration; live elapsed time for active runs")
    total_tokens: int = 0
    message_count: int = 0
    cost: float | None = Field(default=None, description="Estimated spend for this run; null when its models are unpriced")
    error: str | None = Field(default=None, description="Error excerpt for failed runs")


class ConsoleRunsResponse(BaseModel):
    '''分页的跨线程运行列表，最新的在前。'''

    runs: list[ConsoleRunItem]
    has_more: bool


class ConsoleUsageDay(BaseModel):
    '''按本地时间单日汇总的 Token 使用量。'''

    date: str = Field(..., description="Local date (YYYY-MM-DD) per the requested tz offset")
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    runs: int = 0
    cost: float = Field(default=0.0, description="Estimated spend for the day across priced runs")


class ConsoleUsageModelBreakdown(BaseModel):
    '''归因到单个模型的 Token 使用量。'''

    tokens: int = 0
    runs: int = Field(default=0, description="Runs that used this model (non-exclusive)")
    cost: float | None = Field(default=None, description="Estimated spend for this model; null when unpriced")
    input_tokens: int = Field(default=0, description="Input tokens attributed to this model")
    cache_read_tokens: int = Field(default=0, description="Prompt-cache-hit input tokens attributed to this model")


class ConsoleUsageResponse(BaseModel):
    '''时间窗口内按日汇总的 Token 使用序列及按模型明细。'''

    days: list[ConsoleUsageDay]
    by_model: dict[str, ConsoleUsageModelBreakdown]
    total_tokens: int
    total_runs: int
    total_cost: float | None = Field(default=None, description="Estimated spend for the window; null when no pricing is configured")
    currency: str | None = Field(default=None, description="Display currency taken from the first configured pricing entry")


# 辅助函数


def _session_factory_or_503():
    '''返回 SQL 会话工厂；未配置 SQL 后端时返回 503。'''
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL persistence is unavailable; check database.postgres_url and the database service.",
        )
    return sf


def _as_utc(dt: datetime | None) -> datetime | None:
    '''为历史无时区时间戳补上 UTC，保证报表时间可以统一比较。'''
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


# 定价：实际支出估算


class _ModelPricing(NamedTuple):
    '''每百万 Token 的模型定价配置。'''

    input_per_million: float
    output_per_million: float
    currency: str
    # 提示词缓存命中输入 Token 的价格。为 `None` 时按完整输入价格计费，作为未提供
    # 缓存命中折扣或运营方未配置该价格时的保守上界。
    input_cache_hit_per_million: float | None = None


def _build_pricing_map() -> dict[str, _ModelPricing]:
    '''从 `config.yaml` 的 `models[*].pricing` 收集各模型定价。

    `ModelConfig` 允许额外字段，因此运营方可为模型添加例如
    ``pricing: {currency: CNY, input_per_million: 8, output_per_million: 32,
    input_cache_hit_per_million: 0.8}`` 的配置，无需修改模式。定价同时以配置的 `name`
    和提供商 `model` ID（及其小写形式）为键，因为 `token_usage_by_model` 的分桶使用
    提供商报告的模型名称。
    '''
    try:
        models = get_app_config().models
    except Exception:  # pragma: no cover - 防御性处理：成本展示不得导致控制台不可用。
        logger.warning("console: failed to load model pricing from config", exc_info=True)
        return {}

    pricing: dict[str, _ModelPricing] = {}
    for model_cfg in models or []:
        raw = getattr(model_cfg, "pricing", None)
        if not isinstance(raw, dict):
            continue
        try:
            input_price = float(raw.get("input_per_million") or 0)
            output_price = float(raw.get("output_per_million") or 0)
            raw_hit_price = raw.get("input_cache_hit_per_million")
            cache_hit_price = float(raw_hit_price) if raw_hit_price is not None else None
        except (TypeError, ValueError):
            logger.warning("console: ignoring malformed pricing on model %s", model_cfg.name)
            continue
        if input_price <= 0 and output_price <= 0:
            continue
        currency = str(raw.get("currency") or "USD").upper()
        entry = _ModelPricing(input_price, output_price, currency, cache_hit_price)
        for key in (model_cfg.name, getattr(model_cfg, "model", None)):
            if key:
                pricing.setdefault(key, entry)
                pricing.setdefault(key.lower(), entry)
    return pricing


def _pricing_currency(pricing: dict[str, _ModelPricing]) -> str | None:
    '''返回展示货币，即首个配置定价条目的货币（每个部署使用一种货币）。'''
    return next(iter(pricing.values())).currency if pricing else None


def _lookup_pricing(pricing: dict[str, _ModelPricing], model: str | None) -> _ModelPricing | None:
    '''按模型名称查找定价，同时兼容大小写差异。'''
    if not model:
        return None
    return pricing.get(model) or pricing.get(model.lower())


def _token_cost(input_tokens: int, output_tokens: int, price: _ModelPricing, cache_read_tokens: int = 0) -> float:
    '''计算缓存感知的支出：缓存命中输入 Token 按命中价格计费。

    `cache_read_tokens` 会被限制在 `[0, input_tokens]` 区间内，其余输入按完整
    （缓存未命中）输入价格计费。未配置命中价格时，所有输入均按未命中价格计费。
    '''
    cache_read = min(max(int(cache_read_tokens or 0), 0), max(int(input_tokens or 0), 0))
    uncached = max(int(input_tokens or 0), 0) - cache_read
    hit_price = price.input_cache_hit_per_million if price.input_cache_hit_per_million is not None else price.input_per_million
    return (uncached / 1_000_000) * price.input_per_million + (cache_read / 1_000_000) * hit_price + (output_tokens / 1_000_000) * price.output_per_million


def _run_cost(
    pricing: dict[str, _ModelPricing],
    *,
    model_name: str | None,
    total_input_tokens: int | None,
    total_output_tokens: int | None,
    token_usage_by_model: dict | None,
) -> float | None:
    '''估算单次运行的支出；若所用模型均未定价则返回 `None`。

    优先使用按模型明细，以准确覆盖子智能体使用不同模型等多模型运行；旧记录则回退为
    按 `model_name` 的运行级合计。缺少输入/输出拆分的分桶会被跳过，不进行猜测。
    '''
    cost = 0.0
    priced = False
    if isinstance(token_usage_by_model, dict):
        for model, usage in token_usage_by_model.items():
            if not isinstance(usage, dict):
                continue
            price = _lookup_pricing(pricing, model)
            if price is None:
                continue
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            if input_tokens == 0 and output_tokens == 0:
                continue
            cost += _token_cost(input_tokens, output_tokens, price, int(usage.get("cache_read_tokens") or 0))
            priced = True
    if priced:
        return cost
    price = _lookup_pricing(pricing, model_name)
    if price is None:
        return None
    input_tokens = int(total_input_tokens or 0)
    output_tokens = int(total_output_tokens or 0)
    if input_tokens == 0 and output_tokens == 0:
        return None
    return _token_cost(input_tokens, output_tokens, price)


# 端点


@router.get(
    "/stats",
    response_model=ConsoleStatsResponse,
    summary="Console Stats",
    description="Headline counters (runs, threads, agents, tokens) scoped to the current user.",
)
@require_permission("runs", "read")
async def console_stats(request: Request) -> ConsoleStatsResponse:
    '''返回仪表板的标题计数器。'''
    sf = _session_factory_or_503()
    user_id = await get_current_user(request)
    run_where = (RunRow.user_id == user_id,) if user_id else ()
    thread_where = (ThreadMetaRow.user_id == user_id,) if user_id else ()

    pricing = _build_pricing_map()

    async with sf() as session:
        total_runs = await session.scalar(select(func.count()).select_from(RunRow).where(*run_where)) or 0
        active_runs = await session.scalar(select(func.count()).select_from(RunRow).where(RunRow.status.in_(_ACTIVE_STATUSES), *run_where)) or 0
        failed_runs = await session.scalar(select(func.count()).select_from(RunRow).where(RunRow.status.in_(_FAILED_STATUSES), *run_where)) or 0
        total_tokens = await session.scalar(select(func.coalesce(func.sum(RunRow.total_tokens), 0)).where(*run_where)) or 0
        total_threads = await session.scalar(select(func.count()).select_from(ThreadMetaRow).where(*thread_where)) or 0

        total_cost: float | None = None
        if pricing:
            cost_rows = (
                await session.execute(
                    select(
                        RunRow.model_name,
                        RunRow.total_input_tokens,
                        RunRow.total_output_tokens,
                        RunRow.token_usage_by_model,
                    ).where(*run_where)
                )
            ).all()
            cost_sum = 0.0
            for model_name, input_tokens, output_tokens, usage_map in cost_rows:
                cost = _run_cost(
                    pricing,
                    model_name=model_name,
                    total_input_tokens=input_tokens,
                    total_output_tokens=output_tokens,
                    token_usage_by_model=usage_map,
                )
                if cost is not None:
                    cost_sum += cost
            total_cost = round(cost_sum, 6)

    try:
        # 文件系统扫描会在内部解析有效用户：真实请求由 `AuthMiddleware` 设置上下文，
        # 认证禁用模式使用 `"default"`。
        agents = await asyncio.to_thread(list_custom_agents)
        total_agents = len(agents)
    except Exception:  # pragma: no cover - 防御性处理：异常的智能体目录不得使统计接口返回 500。
        logger.warning("console_stats: failed to list custom agents", exc_info=True)
        total_agents = 0

    return ConsoleStatsResponse(
        total_runs=total_runs,
        active_runs=active_runs,
        failed_runs=failed_runs,
        total_threads=total_threads,
        total_agents=total_agents,
        total_tokens=total_tokens,
        total_cost=total_cost,
        currency=_pricing_currency(pricing),
    )


@router.get(
    "/runs",
    response_model=ConsoleRunsResponse,
    summary="List Runs Across Threads",
    description="Cross-thread run history for the current user, newest first, joined with thread titles.",
)
@require_permission("runs", "read")
async def console_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, description="Filter by run status (e.g. running, success, error)"),
) -> ConsoleRunsResponse:
    '''返回用户在所有线程中运行的页面。'''
    sf = _session_factory_or_503()
    user_id = await get_current_user(request)

    stmt = select(RunRow, ThreadMetaRow.display_name).join(ThreadMetaRow, ThreadMetaRow.thread_id == RunRow.thread_id, isouter=True).order_by(RunRow.created_at.desc(), RunRow.run_id.desc()).limit(limit + 1).offset(offset)
    if user_id:
        stmt = stmt.where(RunRow.user_id == user_id)
    if status:
        stmt = stmt.where(RunRow.status == status)

    async with sf() as session:
        rows = (await session.execute(stmt)).all()

    pricing = _build_pricing_map()
    has_more = len(rows) > limit
    now = datetime.now(UTC)
    items: list[ConsoleRunItem] = []
    for row, display_name in rows[:limit]:
        created = _as_utc(row.created_at)
        updated = _as_utc(row.updated_at)
        if row.status in _ACTIVE_STATUSES:
            duration = (now - created).total_seconds() if created else None
        else:
            duration = (updated - created).total_seconds() if created and updated else None
        cost = _run_cost(
            pricing,
            model_name=row.model_name,
            total_input_tokens=row.total_input_tokens,
            total_output_tokens=row.total_output_tokens,
            token_usage_by_model=row.token_usage_by_model,
        )
        items.append(
            ConsoleRunItem(
                run_id=row.run_id,
                thread_id=row.thread_id,
                thread_title=display_name,
                assistant_id=row.assistant_id,
                status=row.status,
                model_name=row.model_name,
                created_at=created,
                updated_at=updated,
                duration_seconds=max(duration, 0.0) if duration is not None else None,
                total_tokens=row.total_tokens or 0,
                message_count=row.message_count or 0,
                cost=round(cost, 6) if cost is not None else None,
                error=row.error[:_ERROR_EXCERPT_CHARS] if row.error else None,
            )
        )
    return ConsoleRunsResponse(runs=items, has_more=has_more)


@router.get(
    "/usage",
    response_model=ConsoleUsageResponse,
    summary="Token Usage Over Time",
    description="Daily token-usage series (zero-filled) plus per-model breakdown over the requested window.",
)
@require_permission("runs", "read")
async def console_usage(
    request: Request,
    days: int = Query(default=14, ge=1, le=90),
    tz_offset_minutes: int = Query(default=0, ge=-840, le=840, description="Local-time offset from UTC for day bucketing"),
) -> ConsoleUsageResponse:
    '''按当地时间和型号汇总令牌使用情况。'''
    sf = _session_factory_or_503()
    user_id = await get_current_user(request)

    tz_delta = timedelta(minutes=tz_offset_minutes)
    today_local = (datetime.now(UTC) + tz_delta).date()
    start_local = today_local - timedelta(days=days - 1)
    window_start_utc = datetime.combine(start_local, time.min, tzinfo=UTC) - tz_delta

    stmt = select(RunRow).where(RunRow.created_at >= window_start_utc)
    if user_id:
        stmt = stmt.where(RunRow.user_id == user_id)

    async with sf() as session:
        rows = (await session.execute(stmt)).scalars().all()

    day_buckets: dict[str, ConsoleUsageDay] = {}
    for i in range(days):
        d = (start_local + timedelta(days=i)).isoformat()
        day_buckets[d] = ConsoleUsageDay(date=d)

    pricing = _build_pricing_map()
    by_model: dict[str, ConsoleUsageModelBreakdown] = {}
    total_tokens = 0
    total_runs = 0
    total_cost = 0.0 if pricing else None
    for row in rows:
        created = _as_utc(row.created_at)
        if created is None:
            continue
        local_date = ((created + tz_delta).date()).isoformat()
        bucket = day_buckets.get(local_date)
        if bucket is None:
            # 该记录位于本地时间窗口之外（UTC 查询范围包含了额外数据），跳过。
            continue
        run_tokens = row.total_tokens or 0
        bucket.total_tokens += run_tokens
        bucket.input_tokens += row.total_input_tokens or 0
        bucket.output_tokens += row.total_output_tokens or 0
        bucket.runs += 1
        total_tokens += run_tokens
        total_runs += 1

        run_cost = _run_cost(
            pricing,
            model_name=row.model_name,
            total_input_tokens=row.total_input_tokens,
            total_output_tokens=row.total_output_tokens,
            token_usage_by_model=row.token_usage_by_model,
        )
        if run_cost is not None and total_cost is not None:
            bucket.cost = round(bucket.cost + run_cost, 6)
            total_cost = round(total_cost + run_cost, 6)

        usage_map = row.token_usage_by_model or {}
        if isinstance(usage_map, dict) and usage_map:
            for model, usage in usage_map.items():
                entry = by_model.setdefault(model, ConsoleUsageModelBreakdown())
                entry.runs += 1
                if not isinstance(usage, dict):
                    continue
                entry.tokens += int(usage.get("total_tokens", 0) or 0)
                entry.input_tokens += int(usage.get("input_tokens") or 0)
                entry.cache_read_tokens += int(usage.get("cache_read_tokens") or 0)
                price = _lookup_pricing(pricing, model)
                if price is not None:
                    model_cost = _token_cost(int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), price, int(usage.get("cache_read_tokens") or 0))
                    entry.cost = round((entry.cost or 0.0) + model_cost, 6)
        elif row.model_name and run_tokens > 0:
            # 早于 `token_usage_by_model` 的旧记录：回退到运行级模型。
            entry = by_model.setdefault(row.model_name, ConsoleUsageModelBreakdown())
            entry.tokens += run_tokens
            entry.runs += 1
            if run_cost is not None:
                entry.cost = round((entry.cost or 0.0) + run_cost, 6)

    return ConsoleUsageResponse(
        days=list(day_buckets.values()),
        by_model=by_model,
        total_tokens=total_tokens,
        total_runs=total_runs,
        total_cost=total_cost,
        currency=_pricing_currency(pricing),
    )
