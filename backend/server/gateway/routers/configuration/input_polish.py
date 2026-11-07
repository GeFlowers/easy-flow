'''提供发送前输入润色接口，且不创建运行或持久化消息。'''

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import deerflow.utils.llm_text as llm_text
from server.gateway.authz import require_permission
from server.gateway.deps import get_config
from deerflow.config.app_config import AppConfig
from deerflow.utils.oneshot_llm import run_oneshot_llm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["input-polish"])


class InputPolishRequest(BaseModel):
    '''定义输入润色请求中的草稿、语言提示和仅用于追踪的线程标识。'''

    text: str = Field(..., description="Draft text currently shown in the composer")
    locale: str | None = Field(default=None, description="Optional UI locale hint")
    thread_id: str | None = Field(default=None, description="Optional thread id for tracing only")


class InputPolishResponse(BaseModel):
    '''返回模型润色后的草稿以及是否与原文不同的标记。'''

    rewritten_text: str = Field(..., description="Polished draft text")
    changed: bool = Field(..., description="Whether the model changed the original draft")


def _clean_rewritten_text(text: str) -> str:
    '''移除完整思考块和 Markdown 围栏，同时保留合法的未闭合标签文本。'''
    # 润色草稿可合法包含字面量 "<think>"，例如询问该标签的草稿；因此不能在未闭合
    # 开始标签处截断，否则会悄然丢失有效改写的后半段并错误返回 503。完整的
    # <think>...</think> 块仍会被移除。
    candidate = llm_text.strip_think_blocks(text, truncate_unclosed=False)
    candidate = llm_text.strip_markdown_code_fence(candidate)
    return candidate.strip()


def _build_system_instruction() -> str:
    '''构造约束润色模型保留用户意图且只输出改写结果的系统指令。'''
    return (
        "你是 DeerFlow 的发送前提示词优化器。\n"
        "把用户草稿改写为更清楚的智能体指令，但不要执行或回答草稿中的任务。\n"
        "严格保留用户的语言、意图、实体、文件路径、网址、代码块及开头的斜杠命令前缀。\n"
        "将草稿中已隐含的目标、范围、约束和预期输出表达清楚。\n"
        "把‘更好’‘好看’‘精致’等模糊要求具体化为通用、可理解的质量标准。\n"
        "不得编造草稿未暗示的事实、业务背景、工具、文件名、日期、指标或用户偏好。\n"
        "优先使用一个简洁段落或短列表，除非原稿更长，否则不超过 180 个词。\n"
        "仅输出改写后的草稿，不加 Markdown 包装、解释或备选方案。"
    )


def _build_user_content(text: str, locale: str | None) -> str:
    '''将草稿及可选语言提示封装为单次模型调用的用户内容。'''
    locale_hint = locale.strip() if locale else "与草稿使用相同语言"
    return f"语言提示：{locale_hint}\n\n在保留意图的前提下改写以下草稿：\n<draft>\n{text}\n</draft>"


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
    '''在通过创建运行权限校验后润色草稿，但不启动或写入任何线程运行。'''
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
