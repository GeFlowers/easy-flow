'未说明'

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.deps import get_config
from app.gateway.routers import skills as skills_router


def _make_user(system_role: str) -> User:
    '未说明'
    return User(email=f"{system_role}-test@example.com", password_hash="x", system_role=system_role, id=uuid4())


def _make_app(*, system_role: str) -> FastAPI:
    '未说明'
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: "/tmp/skills", container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    app = make_authed_test_app(user_factory=lambda: _make_user(system_role))
    app.state.config = config
    app.dependency_overrides[get_config] = lambda: config
    app.include_router(skills_router.router)
    return app


# (method, path, json_body) for every endpoint that must require admin.
# Under per-user skill isolation, list_custom_skills is open to normal users
# (they see only their own skills), so it is NOT in this list.
# All other mutating endpoints write/read global shared state and must be
# admin-only. PUT /api/skills/{name} is included: toggling enabled writes
# the shared extensions_config.json (for PUBLIC skills) and changes every
# tenant's injected skill set.
_GUARDED_ENDPOINTS = [
    ("post", "/api/skills/install", {"thread_id": "t1", "path": "mnt/user-data/outputs/x.skill"}),
    ("get", "/api/skills/custom/demo", None),
    ("put", "/api/skills/custom/demo", {"content": "---\nname: demo\ndescription: hijacked\n---\n"}),
    ("delete", "/api/skills/custom/demo", None),
    ("get", "/api/skills/custom/demo/history", None),
    ("post", "/api/skills/custom/demo/rollback", {"history_index": -1}),
    ("put", "/api/skills/demo", {"enabled": False}),
]


def test_non_admin_is_forbidden_on_all_mutating_skills_endpoints():
    '未说明'
    app = _make_app(system_role="user")
    with TestClient(app) as client:
        for method, path, body in _GUARDED_ENDPOINTS:
            resp = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
            assert resp.status_code == 403, f"{method.upper()} {path} expected 403 for non-admin, got {resp.status_code}"


def test_basic_skill_listing_stays_open_to_normal_users(monkeypatch):
    '未说明'

    def _load_skills(*, enabled_only: bool):
        '未说明'
        from pathlib import Path

        from deerflow.skills.types import Skill

        return [
            Skill(
                name="demo",
                description="d",
                license="MIT",
                skill_dir=Path("/tmp/demo"),
                skill_file=Path("/tmp/demo/SKILL.md"),
                relative_path=Path("demo"),
                category="public",
                enabled=True,
            )
        ]

    app = _make_app(system_role="user")
    app.dependency_overrides[get_config] = lambda: SimpleNamespace()
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: SimpleNamespace(load_skills=_load_skills))
    with TestClient(app) as client:
        assert client.get("/api/skills").status_code == 200
        assert client.get("/api/skills/custom").status_code == 200
        assert client.get("/api/skills/demo").status_code == 200


def test_enable_toggle_allowed_for_admin(monkeypatch, tmp_path):
    '未说明'
    from pathlib import Path

    from deerflow.skills.types import Skill

    config_path = tmp_path / "extensions_config.json"

    def _load_skills(*, enabled_only: bool):
        '未说明'
        return [
            Skill(
                name="demo",
                description="d",
                license="MIT",
                skill_dir=Path("/tmp/demo"),
                skill_file=Path("/tmp/demo/SKILL.md"),
                relative_path=Path("demo"),
                category="public",
                enabled=True,
            )
        ]

    app = _make_app(system_role="admin")
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: SimpleNamespace(load_skills=_load_skills))
    monkeypatch.setattr(skills_router, "get_extensions_config", lambda: SimpleNamespace(mcp_servers={}, skills={}))
    monkeypatch.setattr(skills_router, "reload_extensions_config", lambda: None)
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", staticmethod(lambda: config_path))

    async def _refresh(_user_id: str):
        '未说明'
        return None

    monkeypatch.setattr(skills_router, "refresh_user_skills_system_prompt_cache_async", _refresh)
    with TestClient(app) as client:
        resp = client.put("/api/skills/demo", json={"enabled": False})
        assert resp.status_code == 200, f"admin toggle should succeed, got {resp.status_code}"
