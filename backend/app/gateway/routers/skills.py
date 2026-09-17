"""提供技能查询、安装和管理员专属自定义技能管理路由。"""

import asyncio
import json
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.deps import get_config, require_admin_user
from app.gateway.path_utils import resolve_thread_virtual_path
from deerflow.agents.lead_agent.prompt import clear_skills_system_prompt_cache, refresh_user_skills_system_prompt_cache_async
from deerflow.config.app_config import AppConfig
from deerflow.config.extensions_config import ExtensionsConfig, SkillStateConfig, get_extensions_config, reload_extensions_config
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.skills import Skill
from deerflow.skills.installer import SkillAlreadyExistsError, SkillSecurityScanError
from deerflow.skills.security_scanner import scan_skill_content
from deerflow.skills.security_static_scanner import (
    StaticFinding,
    StaticScanBlockedError,
    StaticScannerError,
    enforce_static_scan,
)
from deerflow.skills.storage import SkillStorage, get_or_new_user_skill_storage
from deerflow.skills.types import SKILL_MD_FILE, SkillCategory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["skills"])

_ADMIN_REQUIRED_DETAIL = "Admin privileges required to manage skills."


class SkillResponse(BaseModel):
    """封装 SkillResponse 的状态、协作关系与公开操作。

    Response model for skill information."""

    name: str = Field(..., description="Name of the skill")
    description: str = Field(..., description="Description of what the skill does")
    license: str | None = Field(None, description="License information")
    category: SkillCategory = Field(..., description="Category of the skill (public, custom, or legacy)")
    enabled: bool = Field(default=True, description="Whether this skill is enabled")
    editable: bool = Field(default=False, description="Whether this skill can be edited/deleted (true only for custom)")


class SkillsListResponse(BaseModel):
    """封装 SkillsListResponse 的状态、协作关系与公开操作。

    Response model for listing all skills."""

    skills: list[SkillResponse]


class SkillUpdateRequest(BaseModel):
    """封装 SkillUpdateRequest 的状态、协作关系与公开操作。

    Request model for updating a skill."""

    enabled: bool = Field(..., description="Whether to enable or disable the skill")


class SkillInstallRequest(BaseModel):
    """封装 SkillInstallRequest 的状态、协作关系与公开操作。

    Request model for installing a skill from a .skill file."""

    thread_id: str = Field(..., description="The thread ID where the .skill file is located")
    path: str = Field(..., description="Virtual path to the .skill file (e.g., mnt/user-data/outputs/my-skill.skill)")


class SkillInstallResponse(BaseModel):
    """封装 SkillInstallResponse 的状态、协作关系与公开操作。

    Response model for skill installation."""

    success: bool = Field(..., description="Whether the installation was successful")
    skill_name: str = Field(..., description="Name of the installed skill")
    message: str = Field(..., description="Installation result message")


class CustomSkillContentResponse(SkillResponse):
    """表示包含原始 SKILL.md 内容的管理员自定义技能响应。"""

    content: str = Field(..., description="Raw SKILL.md content")


class CustomSkillUpdateRequest(BaseModel):
    """定义管理员替换自定义 SKILL.md 内容的请求。"""

    content: str = Field(..., description="Replacement SKILL.md content")


class CustomSkillHistoryResponse(BaseModel):
    """表示管理员可读取的自定义技能修改历史。"""

    history: list[dict]


class SkillRollbackRequest(BaseModel):
    """定义管理员恢复自定义技能历史版本的请求。"""

    history_index: int = Field(default=-1, description="History entry index to restore from, defaulting to the latest change.")


def _skill_to_response(skill: Skill) -> SkillResponse:
    """执行 _skill_to_response 的明确职责，并返回与调用约定一致的结果。

    Convert a Skill object to a SkillResponse."""
    return SkillResponse(
        name=skill.name,
        description=skill.description,
        license=skill.license,
        category=skill.category,
        enabled=skill.enabled,
        editable=skill.category == SkillCategory.CUSTOM,
    )


def _static_scan_http_detail(error: StaticScanBlockedError) -> dict:
    """将静态扫描拦截异常转换为可安全公开的 HTTP 详情。"""
    return {
        "message": str(error),
        "skill_name": error.skill_name,
        "findings": error.findings,
    }


async def _scan_static_skill_markdown_or_raise(skill_name: str, content: str, *, app_config: AppConfig) -> list[StaticFinding]:
    """在临时目录扫描技能 Markdown，命中安全规则时抛出 HTTP 异常。"""

    def _scan_markdown() -> list[StaticFinding]:
        """在工作线程中落盘临时技能包并执行静态扫描。"""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / skill_name
            skill_dir.mkdir(parents=True)
            (skill_dir / SKILL_MD_FILE).write_text(content, encoding="utf-8")
            return enforce_static_scan(skill_dir, skill_name=skill_name, app_config=app_config)

    try:
        return await asyncio.to_thread(_scan_markdown)
    except StaticScanBlockedError as e:
        raise HTTPException(status_code=400, detail=_static_scan_http_detail(e)) from e
    except StaticScannerError as e:
        raise HTTPException(status_code=400, detail=f"Static security scan failed for skill '{skill_name}': {e}") from e


def _get_user_skill_storage(config: AppConfig) -> SkillStorage:
    """执行 _get_user_skill_storage 的明确职责，并返回与调用约定一致的结果。

    Return a user-scoped skill storage for custom skill operations.

        Uses the effective user_id from the request context (set by auth middleware).
        For public skill reads, the global singleton storage is still used.
    """
    return get_or_new_user_skill_storage(get_effective_user_id(), app_config=config)


@router.get(
    "/skills",
    response_model=SkillsListResponse,
    summary="List All Skills",
    description="Retrieve a list of all available skills from both public and custom directories.",
)
async def list_skills(config: AppConfig = Depends(get_config)) -> SkillsListResponse:
    """列出当前用户可见的公共与自定义技能及启用状态。"""
    try:
        # Use user-scoped storage: loads public (global) + custom (user-level + fallback)
        skills = _get_user_skill_storage(config).load_skills(enabled_only=False)
        return SkillsListResponse(skills=[_skill_to_response(skill) for skill in skills])
    except Exception as e:
        logger.error(f"Failed to load skills: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to load skills: {str(e)}")


@router.post(
    "/skills/install",
    response_model=SkillInstallResponse,
    summary="Install Skill",
    description="Install a skill from a .skill file (ZIP archive) located in the thread's user-data directory.",
)
async def install_skill(request: Request, body: SkillInstallRequest, config: AppConfig = Depends(get_config)) -> SkillInstallResponse:
    """仅允许管理员安装技能包，并在安装前执行安全校验。"""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        skill_file_path = resolve_thread_virtual_path(body.thread_id, body.path)
        result = await _get_user_skill_storage(config).ainstall_skill_from_archive(skill_file_path)
        await refresh_user_skills_system_prompt_cache_async(get_effective_user_id())
        return SkillInstallResponse(**result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except SkillAlreadyExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except SkillSecurityScanError as e:
        if e.findings:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": str(e),
                    "skill_name": e.skill_name,
                    "findings": e.findings,
                },
            )
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to install skill: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to install skill: {str(e)}")


@router.get("/skills/custom", response_model=SkillsListResponse, summary="List Custom Skills")
async def list_custom_skills(config: AppConfig = Depends(get_config)) -> SkillsListResponse:
    """收集并返回，并遵守 list_custom_skills 所表达的接口约束。

    List only user-owned custom skills (SkillCategory.CUSTOM).

        Legacy shared skills (SkillCategory.LEGACY) are NOT included here —
        they are read-only and appear in the full ``list_skills`` endpoint.
        The frontend should use ``list_skills`` to display all available
        skills including legacy ones.
    """
    try:
        skills = [skill for skill in _get_user_skill_storage(config).load_skills(enabled_only=False) if skill.category == SkillCategory.CUSTOM]
        return SkillsListResponse(skills=[_skill_to_response(skill) for skill in skills])
    except Exception as e:
        logger.error("Failed to list custom skills: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list custom skills: {str(e)}")


@router.get("/skills/custom/{skill_name}", response_model=CustomSkillContentResponse, summary="Get Custom Skill Content")
async def get_custom_skill(skill_name: str, request: Request, config: AppConfig = Depends(get_config)) -> CustomSkillContentResponse:
    """仅允许管理员读取指定自定义技能的原始内容。"""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    return await _read_custom_skill_response(skill_name, config)


async def _read_custom_skill_response(skill_name: str, config: AppConfig) -> CustomSkillContentResponse:
    """读取并封装已校验名称的自定义技能内容响应。"""
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        storage = _get_user_skill_storage(config)
        skills = storage.load_skills(enabled_only=False)
        skill = next((s for s in skills if s.name == skill_name and s.category == SkillCategory.CUSTOM), None)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Custom skill '{skill_name}' not found")
        return CustomSkillContentResponse(**_skill_to_response(skill).model_dump(), content=storage.read_custom_skill(skill_name))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get custom skill %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get custom skill: {str(e)}")


@router.put("/skills/custom/{skill_name}", response_model=CustomSkillContentResponse, summary="Edit Custom Skill")
async def update_custom_skill(skill_name: str, body: CustomSkillUpdateRequest, request: Request, config: AppConfig = Depends(get_config)) -> CustomSkillContentResponse:
    """仅允许管理员经扫描后更新自定义技能内容。"""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        storage = _get_user_skill_storage(config)
        storage.ensure_custom_skill_is_editable(skill_name)
        storage.validate_skill_markdown_content(skill_name, body.content)
        static_findings = await _scan_static_skill_markdown_or_raise(skill_name, body.content, app_config=config)
        scan = await scan_skill_content(body.content, executable=False, location=f"{skill_name}/{SKILL_MD_FILE}", app_config=config, static_findings=static_findings)
        if scan.decision == "block":
            raise HTTPException(status_code=400, detail=f"Security scan blocked the edit: {scan.reason}")
        prev_content = storage.read_custom_skill(skill_name)
        storage.write_custom_skill(skill_name, SKILL_MD_FILE, body.content)
        storage.append_history(
            skill_name,
            {
                "action": "human_edit",
                "author": "human",
                "thread_id": None,
                "file_path": SKILL_MD_FILE,
                "prev_content": prev_content,
                "new_content": body.content,
                "scanner": {"decision": scan.decision, "reason": scan.reason, "static_findings": static_findings},
            },
        )
        await refresh_user_skills_system_prompt_cache_async(get_effective_user_id())
        return await _read_custom_skill_response(skill_name, config)
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to update custom skill %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update custom skill: {str(e)}")


@router.delete("/skills/custom/{skill_name}", summary="Delete Custom Skill")
async def delete_custom_skill(skill_name: str, request: Request, config: AppConfig = Depends(get_config)) -> dict[str, bool]:
    """仅允许管理员删除指定自定义技能。"""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        storage = _get_user_skill_storage(config)
        storage.delete_custom_skill(
            skill_name,
            history_meta={
                "action": "human_delete",
                "author": "human",
                "thread_id": None,
                "file_path": SKILL_MD_FILE,
                "prev_content": None,
                "new_content": None,
                "scanner": {"decision": "allow", "reason": "Deletion requested."},
            },
        )
        await refresh_user_skills_system_prompt_cache_async(get_effective_user_id())
        return {"success": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to delete custom skill %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete custom skill: {str(e)}")


@router.get("/skills/custom/{skill_name}/history", response_model=CustomSkillHistoryResponse, summary="Get Custom Skill History")
async def get_custom_skill_history(skill_name: str, request: Request, config: AppConfig = Depends(get_config)) -> CustomSkillHistoryResponse:
    """仅允许管理员读取自定义技能的版本历史。"""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        storage = _get_user_skill_storage(config)
        if not storage.custom_skill_exists(skill_name) and not storage.get_skill_history_file(skill_name).exists():
            raise HTTPException(status_code=404, detail=f"Custom skill '{skill_name}' not found")
        return CustomSkillHistoryResponse(history=storage.read_history(skill_name))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to read history for %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read history: {str(e)}")


@router.post("/skills/custom/{skill_name}/rollback", response_model=CustomSkillContentResponse, summary="Rollback Custom Skill")
async def rollback_custom_skill(skill_name: str, body: SkillRollbackRequest, request: Request, config: AppConfig = Depends(get_config)) -> CustomSkillContentResponse:
    """仅允许管理员将自定义技能恢复到指定历史版本。"""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        storage = _get_user_skill_storage(config)
        if not storage.custom_skill_exists(skill_name) and not storage.get_skill_history_file(skill_name).exists():
            raise HTTPException(status_code=404, detail=f"Custom skill '{skill_name}' not found")
        history = storage.read_history(skill_name)
        if not history:
            raise HTTPException(status_code=400, detail=f"Custom skill '{skill_name}' has no history")
        record = history[body.history_index]
        target_content = record.get("prev_content")
        if target_content is None:
            raise HTTPException(status_code=400, detail="Selected history entry has no previous content to roll back to")
        storage.validate_skill_markdown_content(skill_name, target_content)
        static_findings = await _scan_static_skill_markdown_or_raise(skill_name, target_content, app_config=config)
        scan = await scan_skill_content(target_content, executable=False, location=f"{skill_name}/{SKILL_MD_FILE}", app_config=config, static_findings=static_findings)
        skill_file = storage.get_custom_skill_file(skill_name)
        current_content = skill_file.read_text(encoding="utf-8") if skill_file.exists() else None
        history_entry = {
            "action": "rollback",
            "author": "human",
            "thread_id": None,
            "file_path": SKILL_MD_FILE,
            "prev_content": current_content,
            "new_content": target_content,
            "rollback_from_ts": record.get("ts"),
            "scanner": {"decision": scan.decision, "reason": scan.reason, "static_findings": static_findings},
        }
        if scan.decision == "block":
            storage.append_history(skill_name, history_entry)
            raise HTTPException(status_code=400, detail=f"Rollback blocked by security scanner: {scan.reason}")
        storage.write_custom_skill(skill_name, SKILL_MD_FILE, target_content)
        storage.append_history(skill_name, history_entry)
        await refresh_user_skills_system_prompt_cache_async(get_effective_user_id())
        return await _read_custom_skill_response(skill_name, config)
    except HTTPException:
        raise
    except IndexError:
        raise HTTPException(status_code=400, detail="history_index is out of range")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to roll back custom skill %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to roll back custom skill: {str(e)}")


@router.get(
    "/skills/{skill_name}",
    response_model=SkillResponse,
    summary="Get Skill Details",
    description="Retrieve detailed information about a specific skill by its name.",
)
async def get_skill(skill_name: str, config: AppConfig = Depends(get_config)) -> SkillResponse:
    """读取当前用户可见的单个技能元数据。"""
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        skills = _get_user_skill_storage(config).load_skills(enabled_only=False)
        skill = next((s for s in skills if s.name == skill_name), None)

        if skill is None:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

        return _skill_to_response(skill)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get skill {skill_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get skill: {str(e)}")


@router.put(
    "/skills/{skill_name}",
    response_model=SkillResponse,
    summary="Update Skill",
    description="Update a skill's enabled status by modifying the extensions_config.json file.",
)
async def update_skill(skill_name: str, body: SkillUpdateRequest, request: Request, config: AppConfig = Depends(get_config)) -> SkillResponse:
    """仅允许管理员更新共享技能启用状态并刷新全局代理配置。"""
    # Enabling/disabling a skill writes the shared extensions_config.json and
    # refreshes the system prompt for every tenant, so it is a global mutation
    # (there is no per-user skill state). Guard it as admin-only like the other
    # global config writes, matching the MCP router.
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        storage = _get_user_skill_storage(config)
        skills = storage.load_skills(enabled_only=False)
        skill = next((s for s in skills if s.name == skill_name), None)

        if skill is None:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

        # PUBLIC skills → global extensions_config.json (shared state).
        # CUSTOM / LEGACY skills → per-user _skill_states.json (isolated state)
        # so that two users with same-named custom skills can toggle independently.
        if skill.category == SkillCategory.PUBLIC:
            config_path = ExtensionsConfig.resolve_config_path()
            if config_path is None:
                config_path = Path.cwd().parent / "extensions_config.json"
                logger.info(f"No existing extensions config found. Creating new config at: {config_path}")

            extensions_config = get_extensions_config()
            extensions_config.skills[skill_name] = SkillStateConfig(enabled=body.enabled)

            config_data = {
                "mcpServers": {name: server.model_dump() for name, server in extensions_config.mcp_servers.items()},
                "skills": {name: {"enabled": skill_config.enabled} for name, skill_config in extensions_config.skills.items()},
            }

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)

            logger.info(f"Skills configuration updated and saved to: {config_path}")
            reload_extensions_config()
        else:
            # CUSTOM / LEGACY: write per-user state
            from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

            if isinstance(storage, UserScopedSkillStorage):
                storage.set_skill_enabled_state(skill_name, body.enabled)
            else:
                # Fallback for non-user-scoped storage (unlikely in practice)
                config_path = ExtensionsConfig.resolve_config_path()
                if config_path is None:
                    config_path = Path.cwd().parent / "extensions_config.json"
                extensions_config = get_extensions_config()
                extensions_config.skills[skill_name] = SkillStateConfig(enabled=body.enabled)
                config_data = {
                    "mcpServers": {name: server.model_dump() for name, server in extensions_config.mcp_servers.items()},
                    "skills": {name: {"enabled": skill_config.enabled} for name, skill_config in extensions_config.skills.items()},
                }
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=2)
                reload_extensions_config()

        # PUBLIC skill enabled state lives in the global extensions_config.json
        # and affects every user, so the prompt cache for ALL users must be
        # invalidated. CUSTOM/LEGACY skill state is per-user so only that
        # user's cache needs to be dropped.
        if skill.category == SkillCategory.PUBLIC:
            # clear_skills_system_prompt_cache is sync; run it in a worker
            # thread to avoid blocking the event loop. The lock inside it is
            # cheap, but the async drop also keeps the test mock surface
            # consistent (tests patch the async variant).
            await asyncio.to_thread(clear_skills_system_prompt_cache)
        else:
            await refresh_user_skills_system_prompt_cache_async(get_effective_user_id())

        skills = _get_user_skill_storage(config).load_skills(enabled_only=False)
        updated_skill = next((s for s in skills if s.name == skill_name), None)

        if updated_skill is None:
            raise HTTPException(status_code=500, detail=f"Failed to reload skill '{skill_name}' after update")

        logger.info(f"Skill '{skill_name}' enabled status updated to {body.enabled}")
        return _skill_to_response(updated_skill)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update skill {skill_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update skill: {str(e)}")
