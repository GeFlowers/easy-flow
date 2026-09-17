# DeerFlow - 统一开发环境入口

.PHONY: help config config-upgrade check install setup doctor support-bundle detect-thread-boundaries detect-blocking-io dev dev-daemon start start-daemon stop clean docker-init docker-start docker-stop docker-logs docker-logs-frontend docker-logs-gateway docker-logs-postgres

BASH ?= bash
BACKEND_UV_RUN = cd backend && uv run

# 检测 Windows，并将 Shell 脚本转交 Git Bash，避免 cmd.exe/PowerShell 的语法差异。
ifeq ($(OS),Windows_NT)
    SHELL := cmd.exe
    PYTHON ?= python
    # 从 cmd.exe / PowerShell 启动 Make 时，通过 Git Bash 运行仓库 Shell 脚本。
    RUN_WITH_GIT_BASH = call scripts\run-with-git-bash.cmd
else
    PYTHON ?= python3
    RUN_WITH_GIT_BASH =
endif

help:
	@echo "DeerFlow Development Commands:"
	@echo "  make setup           - Interactive setup wizard (recommended for new users)"
	@echo "  make doctor          - Check configuration and system requirements"
	@echo "  make support-bundle  - Create a redacted issue summary, AI draft, and evidence bundle"
	@echo "  make config          - Generate local config files (aborts if config already exists)"
	@echo "  make config-upgrade  - Merge new fields from config.example.yaml into config.yaml"
	@echo "  make check           - Check if all required tools are installed"
	@echo "  make detect-thread-boundaries - Inventory async/thread boundary points"
	@echo "  make detect-blocking-io        - Inventory blocking IO that may block the backend event loop"
	@echo "  make install         - Install all dependencies (frontend + backend + pre-commit hooks)"
	@echo "  make setup-sandbox   - Pre-pull sandbox container image (recommended)"
	@echo "  make dev             - Start all services in development mode (with hot-reloading)"
	@echo "  make dev-daemon      - Start dev services in background (daemon mode)"
	@echo "  make start           - Start all services in production mode (optimized, no hot-reloading)"
	@echo "  make start-daemon    - Start prod services in background (daemon mode)"
	@echo "  make stop            - Stop all running services"
	@echo "  make clean           - Clean up processes and temporary files"
	@echo ""
	@echo "Docker Development Commands:"
	@echo "  make docker-init     - Check the Docker environment"
	@echo "  make docker-start    - Start Docker development services (localhost:2026)"
	@echo "  make docker-stop     - Stop Docker development services"
	@echo "  make docker-logs     - View Docker development logs"
	@echo "  make docker-logs-frontend - View Docker frontend logs"
	@echo "  make docker-logs-gateway - View Docker gateway logs"
	@echo "  make docker-logs-postgres - View Docker PostgreSQL logs"

## 初始化与诊断：只生成或检查本地配置，不启动服务
setup:
	@$(BACKEND_UV_RUN) python ../scripts/setup_wizard.py

doctor:
	@$(BACKEND_UV_RUN) python ../scripts/doctor.py

support-bundle:
	@$(BACKEND_UV_RUN) python ../scripts/support_bundle.py --include-doctor

detect-thread-boundaries:
	@$(PYTHON) ./scripts/detect_thread_boundaries.py

detect-blocking-io:
	@$(MAKE) -C backend detect-blocking-io

config:
	@$(PYTHON) ./scripts/configure.py

config-upgrade:
	@$(RUN_WITH_GIT_BASH) ./scripts/config-upgrade.sh

# 依赖检查：在安装或启动前尽早报告缺失工具。
check:
	@$(PYTHON) ./scripts/check.py

# 安装全部依赖与 Git 钩子；不会启动服务。
install:
	@echo "Installing backend dependencies..."
	@cd backend && uv sync
	@echo "Installing frontend dependencies..."
	@cd frontend && pnpm install
	@echo "Installing pre-commit hooks..."
	@uv tool install pre-commit
	@pre-commit install --overwrite
	@echo "✓ All dependencies installed"
	@echo ""
	@echo "=========================================="
	@echo "  Optional: Pre-pull Sandbox Image"
	@echo "=========================================="
	@echo ""
	@echo "If you plan to use Docker/Container-based sandbox, you can pre-pull the image:"
	@echo "  make setup-sandbox"
	@echo ""

# 可选预拉取沙箱镜像，缩短首次容器沙箱启动时间。
setup-sandbox:
	@$(RUN_WITH_GIT_BASH) ./scripts/setup-sandbox.sh

# 开发服务组：启用热重载并在启动前执行依赖检查。
dev:
	@$(PYTHON) ./scripts/check.py
	@$(RUN_WITH_GIT_BASH) ./scripts/serve.sh --dev

# 生产服务组：使用优化模式且不启用热重载。
start:
	@$(PYTHON) ./scripts/check.py
	@$(RUN_WITH_GIT_BASH) ./scripts/serve.sh --prod

# 后台开发服务组：启动后返回调用终端。
dev-daemon:
	@$(PYTHON) ./scripts/check.py
	@$(RUN_WITH_GIT_BASH) ./scripts/serve.sh --dev --daemon

# 后台生产服务组：启动后返回调用终端。
start-daemon:
	@$(PYTHON) ./scripts/check.py
	@$(RUN_WITH_GIT_BASH) ./scripts/serve.sh --prod --daemon

# 仅停止 DeerFlow 所属服务；停止逻辑会保留无关项目进程。
stop:
	@$(RUN_WITH_GIT_BASH) ./scripts/serve.sh --stop

# 清理运行时目录与日志；依赖 stop 先释放 DeerFlow 服务资源。
clean: stop
	@echo "Cleaning up..."
	@-rm -rf backend/.deer-flow 2>/dev/null || true
	@-rm -rf logs/*.log 2>/dev/null || true
	@echo "✓ Cleanup complete"

# ==========================================
# Docker 开发命令：按 config.yaml 的沙箱模式选择服务和权限边界。
# ==========================================

# 检查 Docker 客户端和守护进程是否可用。
docker-init:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh init

# 启动 Docker 开发环境。
docker-start:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh start

# 停止 Docker 开发环境。
docker-stop:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh stop

# 跟随全部 Docker 开发服务日志。
docker-logs:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh logs

# 仅跟随前端 Docker 服务日志。
docker-logs-frontend:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh logs --frontend
docker-logs-gateway:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh logs --gateway
docker-logs-postgres:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh logs --postgres
