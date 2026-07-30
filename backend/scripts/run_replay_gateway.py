"""本脚本负责运行 回放 网关。安全边界：仅处理显式指定的输入与路径，不作为常驻生产服务入口。"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "tests"))  # replay_provider + build_config_yaml live here


def main() -> int:
    '未说明'
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--fixture", default=str(_BACKEND / "tests" / "fixtures" / "replay" / "write_read_file.ultra.json"))
    parser.add_argument("--cors", default="http://localhost:3000")
    args = parser.parse_args()

    from _replay_fixture import REPLAY_MODEL_BLOCK, build_config_yaml, prepare_hermetic_extras

    home = Path(tempfile.mkdtemp(prefix="replay-gw-"))
    cfg = home / "config.yaml"
    cfg.write_text(build_config_yaml(model_block=REPLAY_MODEL_BLOCK, home=home), encoding="utf-8")

    # Override (not setdefault): the replay gateway must be hermetic, so an outer
    # DEER_FLOW_HOME can't leak in and shift prompt-affecting paths/skills.
    os.environ["DEER_FLOW_HOME"] = str(home)
    os.environ["DEER_FLOW_CONFIG_PATH"] = str(cfg)
    os.environ["DEER_FLOW_EXTENSIONS_CONFIG_PATH"] = str(prepare_hermetic_extras(home))
    os.environ["DEERFLOW_REPLAY_FIXTURE"] = args.fixture
    os.environ.setdefault("AUTH_JWT_SECRET", "ci-replay-secret")
    os.environ["GATEWAY_CORS_ORIGINS"] = args.cors
    # Child / dynamic imports (resolve_class) search PYTHONPATH too.
    os.environ["PYTHONPATH"] = os.pathsep.join(p for p in (str(_BACKEND), str(_BACKEND / "tests"), os.environ.get("PYTHONPATH", "")) if p)

    import uvicorn

    target: str | object = "app.gateway.app:app"
    # Test-only: attach the run/message seeder used by the multi-run render-order
    # e2e (#3352). Imported from tests/ and mounted here only — never in the
    # production app. Pass the app object (not the import string) so the extra
    # router is registered before uvicorn serves it.
    if os.environ.get("DEERFLOW_ENABLE_TEST_SEED") == "1":
        from seed_runs_router import router as seed_router

        from app.gateway.app import app as gateway_app

        gateway_app.include_router(seed_router)
        target = gateway_app
        print("[replay-gw] test-only seed router mounted at /api/test-only/seed-runs", flush=True)

    print(f"[replay-gw] config={cfg} fixture={args.fixture} cors={args.cors} port={args.port}", flush=True)
    uvicorn.run(target, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
