'定义 credential_loader 模块提供的职责与可复用接口。\n\nAuto-load credentials from Claude Code CLI and Codex CLI.\n\nImplements two credential strategies:\n  1. Claude Code OAuth token from explicit env vars or an exported credentials file\n     - Uses Authorization: Bearer header (NOT x-api-key)\n     - Requires anthropic-beta: oauth-2025-04-20,claude-code-20250219\n     - Supports $CLAUDE_CODE_OAUTH_TOKEN, $CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR, and $ANTHROPIC_AUTH_TOKEN\n     - Override path with $CLAUDE_CODE_CREDENTIALS_PATH\n  2. Codex CLI token from ~/.codex/auth.json\n     - Uses chatgpt.com/backend-api/codex/responses endpoint\n     - Supports both legacy top-level tokens and current nested tokens shape\n     - Override path with $CODEX_AUTH_PATH\n'

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Required beta headers for Claude Code OAuth tokens
OAUTH_ANTHROPIC_BETAS = "oauth-2025-04-20,claude-code-20250219,interleaved-thinking-2025-05-14"


def is_oauth_token(token: str) -> bool:
    '判断条件是否成立并返回布尔结果，并遵守 is_oauth_token 所表达的接口约束。\n\nCheck if a token is a Claude Code OAuth token (not a standard API key).'
    return isinstance(token, str) and "sk-ant-oat" in token


@dataclass
class ClaudeCodeCredential:
    '封装 ClaudeCodeCredential 的状态、协作关系与公开操作。\n\nClaude Code CLI OAuth credential.'

    access_token: str
    refresh_token: str = ""
    expires_at: int = 0
    source: str = ""

    @property
    def is_expired(self) -> bool:
        '判断条件是否成立并返回布尔结果，并遵守 is_expired 所表达的接口约束'
        if self.expires_at <= 0:
            return False
        return time.time() * 1000 > self.expires_at - 60_000  # 1 min buffer


@dataclass
class CodexCliCredential:
    '封装 CodexCliCredential 的状态、协作关系与公开操作。\n\nCodex CLI credential.'

    access_token: str
    account_id: str = ""
    source: str = ""


def _resolve_credential_path(env_var: str, default_relative_path: str) -> Path:
    '执行 _resolve_credential_path 的明确职责，并返回与调用约定一致的结果'
    configured_path = os.getenv(env_var)
    if configured_path:
        return Path(configured_path).expanduser()
    return _home_dir() / default_relative_path


def _home_dir() -> Path:
    '执行 _home_dir 的明确职责，并返回与调用约定一致的结果'
    home = os.getenv("HOME")
    if home:
        return Path(home).expanduser()
    return Path.home()


def _load_json_file(path: Path, label: str) -> dict[str, Any] | None:
    '执行 _load_json_file 的明确职责，并返回与调用约定一致的结果'
    if not path.exists():
        logger.debug(f"{label} not found: {path}")
        return None
    if path.is_dir():
        logger.warning(f"{label} path is a directory, expected a file: {path}")
        return None

    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read {label}: {e}")
        return None


def _read_secret_from_file_descriptor(env_var: str) -> str | None:
    '执行 _read_secret_from_file_descriptor 的明确职责，并返回与调用约定一致的结果'
    fd_value = os.getenv(env_var)
    if not fd_value:
        return None

    try:
        fd = int(fd_value)
    except ValueError:
        logger.warning(f"{env_var} must be an integer file descriptor, got: {fd_value}")
        return None

    try:
        secret = os.read(fd, 1024 * 1024).decode().strip()
    except OSError as e:
        logger.warning(f"Failed to read {env_var}: {e}")
        return None

    return secret or None


def _credential_from_direct_token(access_token: str, source: str) -> ClaudeCodeCredential | None:
    '执行 _credential_from_direct_token 的明确职责，并返回与调用约定一致的结果'
    token = access_token.strip()
    if not token:
        return None
    return ClaudeCodeCredential(access_token=token, source=source)


def _iter_claude_code_credential_paths() -> list[Path]:
    '执行 _iter_claude_code_credential_paths 的明确职责，并返回与调用约定一致的结果'
    paths: list[Path] = []
    override_path = os.getenv("CLAUDE_CODE_CREDENTIALS_PATH")
    if override_path:
        paths.append(Path(override_path).expanduser())

    default_path = _home_dir() / ".claude/.credentials.json"
    if not paths or paths[-1] != default_path:
        paths.append(default_path)

    return paths


def _extract_claude_code_credential(data: dict[str, Any], source: str) -> ClaudeCodeCredential | None:
    '执行 _extract_claude_code_credential 的明确职责，并返回与调用约定一致的结果'
    oauth = data.get("claudeAiOauth", {})
    access_token = oauth.get("accessToken", "")
    if not access_token:
        logger.debug("Claude Code credentials container exists but no accessToken found")
        return None

    cred = ClaudeCodeCredential(
        access_token=access_token,
        refresh_token=oauth.get("refreshToken", ""),
        expires_at=oauth.get("expiresAt", 0),
        source=source,
    )

    if cred.is_expired:
        logger.warning("Claude Code OAuth token is expired. Run 'claude' to refresh.")
        return None

    return cred


def load_claude_code_credential() -> ClaudeCodeCredential | None:
    '加载并返回，并遵守 load_claude_code_credential 所表达的接口约束。\n\nLoad OAuth credential from explicit Claude Code handoff sources.\n\n    Lookup order:\n      1. $CLAUDE_CODE_OAUTH_TOKEN or $ANTHROPIC_AUTH_TOKEN\n      2. $CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR\n      3. $CLAUDE_CODE_CREDENTIALS_PATH\n      4. ~/.claude/.credentials.json\n\n    Exported credentials files contain:\n    {\n      "claudeAiOauth": {\n        "accessToken": "sk-ant-oat01-...",\n        "refreshToken": "sk-ant-ort01-...",\n        "expiresAt": 1773430695128,\n        "scopes": ["user:inference", ...],\n        ...\n      }\n    }\n    '
    direct_token = os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or os.getenv("ANTHROPIC_AUTH_TOKEN")
    if direct_token:
        cred = _credential_from_direct_token(direct_token, "claude-cli-env")
        if cred:
            logger.info("Loaded Claude Code OAuth credential from environment")
        return cred

    fd_token = _read_secret_from_file_descriptor("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR")
    if fd_token:
        cred = _credential_from_direct_token(fd_token, "claude-cli-fd")
        if cred:
            logger.info("Loaded Claude Code OAuth credential from file descriptor")
        return cred

    override_path = os.getenv("CLAUDE_CODE_CREDENTIALS_PATH")
    override_path_obj = Path(override_path).expanduser() if override_path else None
    for cred_path in _iter_claude_code_credential_paths():
        data = _load_json_file(cred_path, "Claude Code credentials")
        if data is None:
            continue
        cred = _extract_claude_code_credential(data, "claude-cli-file")
        if cred:
            source_label = "override path" if override_path_obj is not None and cred_path == override_path_obj else "plaintext file"
            logger.info(f"Loaded Claude Code OAuth credential from {source_label} (expires_at={cred.expires_at})")
            return cred

    return None


def load_codex_cli_credential() -> CodexCliCredential | None:
    '加载并返回，并遵守 load_codex_cli_credential 所表达的接口约束。\n\nLoad credential from Codex CLI (~/.codex/auth.json).'
    cred_path = _resolve_credential_path("CODEX_AUTH_PATH", ".codex/auth.json")
    data = _load_json_file(cred_path, "Codex CLI credentials")
    if data is None:
        return None
    tokens = data.get("tokens", {})
    if not isinstance(tokens, dict):
        tokens = {}

    access_token = data.get("access_token") or data.get("token") or tokens.get("access_token", "")
    account_id = data.get("account_id") or tokens.get("account_id", "")
    if not access_token:
        logger.debug("Codex CLI credentials file exists but no token found")
        return None

    logger.info("Loaded Codex CLI credential")
    return CodexCliCredential(
        access_token=access_token,
        account_id=account_id,
        source="codex-cli",
    )
