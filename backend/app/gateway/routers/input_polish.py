"""提供发送前输入润色接口，且不创建运行或持久化消息。"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import deerflow.utils.llm_text as llm_text
from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig
from deerflow.utils.oneshot_llm import run_oneshot_llm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["input-polish"])


class InputPolishRequest(BaseModel):
    """定义输入润色请求中的草稿、语言提示和仅用于追踪的线程标识。"""

    text: str = Field(..., description="Draft text currently shown in the composer")
    locale: str | None = Field(default=None, description="Optional UI locale hint")
    thread_id: str | None = Field(default=None, description="Optional thread id for tracing only")


class InputPolishResponse(BaseModel):
    """返回模型润色后的草稿以及是否与原文不同的标记。"""

    rewritten_text: str = Field(..., description="Polished draft text")
    changed: bool = Field(..., description="Whether the model changed the original draft")


def _clean_rewritten_text(text: str) -> str:
    """移除完整思考块和 Markdown 围栏，同时保留合法的未闭合标签文本。"""
    # 润色草稿可合法包含字面量 "<think>"，例如询问该标签的草稿；因此不能在未闭合
    # 开始标签处截断，否则会悄然丢失有效改写的后半段并错误返回 503。完整的
    # <think>...</think> 块仍会被移除。
    candidate = llm_text.strip_think_blocks(text, truncate_unclosed=False)
    candidate = llm_text.strip_markdown_code_fence(candidate)
    return candidate.strip()


def _build_system_instruction() -> str:
    """构造约束润色模型保留用户意图且只输出改写结果的系统指令。"""
    return (
        "You are DeerFlow's pre-send prompt optimizer.\n"
        "Rewrite the user's rough draft into a clearer instruction for an AI agent before it is sent.\n"
        "Do not answer the task.\n"
        "Preserve the user's language, intent, entities, file paths, URLs, code blocks, and any leading slash command prefix exactly.\n"
        "Improve the draft by making the goal, scope, constraints, and desired output explicit when they are implied by the draft.\n"
        "For vague quality words such as 'better', 'good-looking', or 'polished', translate them into concrete but generic quality criteria.\n"
        "Do not invent facts, business context, tools, file names, dates, metrics, or user preferences that are not implied.\n"
        "Prefer one concise paragraph or a short bullet list. Keep it under 180 words unless the original draft is longer.\n"
        "Output only the rewritten draft, with no markdown wrapper, explanation, or alternatives."
    )


def _build_user_content(text: str, locale: str | None) -> str:
    """将草稿及可选语言提示封装为单次模型调用的用户内容。"""
    locale_hint = locale.strip() if locale else "same language as the draft"
    return f"Locale hint: {locale_hint}\n\nRewrite this draft while preserving its intent:\n<draft>\n{text}\n</draft>"


@router.post(
    "/input-polish",
    response_model=InputPolishResponse,
    summary="Polish Composer Input",
    description="Rewrite a draft message before it is sent. This does not create a thread run or persist any message.",
)
@require_permission("runs", "create")
async def polish_input(
    body: InputPolishRequest,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> InputPolishResponse:
    """在通过创建运行权限校验后润色草稿，但不启动或写入任何线程运行。"""
    del request  # 认证装饰器要求保留该参数。

    if not config.input_polish.enabled:
        raise HTTPException(status_code=404, detail="Input polishing is disabled")

    # 校验与发送给模型完全相同的规范化输入，避免用户可见长度边界与模型输入不一致，
    # 例如填充空白的草稿通过校验却带着多余空白传给模型。
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Input text is required")

    max_chars = config.input_polish.max_chars
    if len(text) > max_chars:
        raise HTTPException(status_code=400, detail=f"Input text exceeds {max_chars} characters")

    model_name = config.input_polish.model_name
    try:
        raw = await run_oneshot_llm(
            system_instruction=_build_system_instruction(),
            user_content=_build_user_content(text, body.locale),
            run_name="input_polish",
            app_config=config,
            model_name=model_name,
            thread_id=body.thread_id,
        )
        rewritten = _clean_rewritten_text(raw)
    except Exception as exc:
        logger.exception("Failed to polish input: thread_id=%s err=%s", body.thread_id, exc)
        raise HTTPException(status_code=503, detail="Failed to polish input") from exc

    if not rewritten:
        raise HTTPException(status_code=503, detail="Failed to polish input")

    return InputPolishResponse(
        rewritten_text=rewritten,
        changed=rewritten != text,
    )
