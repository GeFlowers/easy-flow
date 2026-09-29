# DeerFlow - 项目命令入口

.PHONY: help config-upgrade install docker-init docker-start docker-stop docker-logs docker-logs-frontend docker-logs-gateway docker-logs-postgres

# 检测 Windows，并将 Shell 脚本转交 Git Bash，避免 cmd.exe/PowerShell 的语法差异。
ifeq ($(OS),Windows_NT)
    SHELL := cmd.exe
    # 从 cmd.exe / PowerShell 启动 Make 时，通过 Git Bash 运行仓库 Shell 脚本。
    RUN_WITH_GIT_BASH = call scripts\run-with-git-bash.cmd
else
    RUN_WITH_GIT_BASH =
endif

help:
	@echo "DeerFlow Commands:"
	@echo "  make config-upgrade  - Merge new fields from config.example.yaml into config.yaml"
	@echo "  make install         - Install all dependencies (frontend + backend + pre-commit hooks)"
	@echo ""
	@echo "Docker Commands:"
	@echo "  make docker-init     - Check the Docker environment"
	@echo "  make docker-start    - Build and start the application (localhost:2026)"
	@echo "  make docker-stop     - Stop Docker services"
	@echo "  make docker-logs     - View Docker service logs"
	@echo "  make docker-logs-frontend - View Docker frontend logs"
	@echo "  make docker-logs-gateway - View Docker gateway logs"
	@echo "  make docker-logs-postgres - View Docker PostgreSQL logs"

config-upgrade:
	@$(RUN_WITH_GIT_BASH) ./scripts/config-upgrade.sh

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
# ==========================================
# Docker 命令：按 config.yaml 的沙箱模式选择服务和权限边界。
# ==========================================

# 检查 Docker 客户端和守护进程是否可用。
docker-init:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh init

# 构建并启动唯一支持的 Docker 部署。
docker-start:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh start

# 停止 Docker 服务。
docker-stop:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh stop

# 跟随全部 Docker 服务日志。
docker-logs:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh logs

# 仅跟随前端 Docker 服务日志。
docker-logs-frontend:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh logs --frontend
docker-logs-gateway:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh logs --gateway
docker-logs-postgres:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh logs --postgres
