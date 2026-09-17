#!/usr/bin/env bash
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$PROJECT_ROOT/docker"
COMPOSE=(docker compose --env-file "$PROJECT_ROOT/.env" -p deer-flow-dev -f docker-compose-dev.yaml)

cleanup() {
    echo ""
    echo -e "${YELLOW}Operation interrupted by user${NC}"
    exit 130
}

trap cleanup INT TERM

docker_available() {
    command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
}

load_proxy_env_from_dotenv() {
    local env_file="$PROJECT_ROOT/.env"
    local var line value

    [ -f "$env_file" ] || return 0

    for var in HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY http_proxy https_proxy all_proxy no_proxy; do
        if [ -z "${!var+x}" ]; then
            line="$(grep -E "^[[:space:]]*${var}=" "$env_file" | tail -n 1 || true)"
            if [ -n "$line" ]; then
                value="${line#*=}"
                value="${value%\"}"
                value="${value#\"}"
                value="${value%\'}"
                value="${value#\'}"
                value="${value%$'\r'}"
                export "${var}=${value}"
            fi
        fi
    done
}

init() {
    echo "=========================================="
    echo "  DeerFlow Docker Environment Check"
    echo "=========================================="
    echo ""

    if ! docker_available; then
        echo -e "${YELLOW}Docker is not installed or the Docker daemon is not reachable.${NC}"
        exit 1
    fi

    echo -e "${GREEN}Docker is ready.${NC}"
    echo -e "${BLUE}This project uses LocalSandboxProvider, so no sandbox image is required.${NC}"
    echo "Next step: make docker-start"
}

ensure_config_files() {
    if [ ! -f "$PROJECT_ROOT/config.yaml" ]; then
        if [ ! -f "$PROJECT_ROOT/config.example.yaml" ]; then
            echo -e "${YELLOW}config.yaml and config.example.yaml are both missing.${NC}"
            exit 1
        fi
        cp "$PROJECT_ROOT/config.example.yaml" "$PROJECT_ROOT/config.yaml"
        echo -e "${YELLOW}Created config.yaml from config.example.yaml.${NC}"
        echo "Edit config.yaml, then run make docker-start again."
        exit 0
    fi

    if [ ! -f "$PROJECT_ROOT/extensions_config.json" ]; then
        if [ -f "$PROJECT_ROOT/extensions_config.example.json" ]; then
            cp "$PROJECT_ROOT/extensions_config.example.json" "$PROJECT_ROOT/extensions_config.json"
        else
            printf '{}\n' > "$PROJECT_ROOT/extensions_config.json"
        fi
        echo -e "${BLUE}Created extensions_config.json${NC}"
    fi
}

start() {
    if [ "$#" -gt 0 ]; then
        echo -e "${YELLOW}Unknown option for start: $1${NC}"
        echo "Usage: $0 start"
        exit 1
    fi

    if ! docker_available; then
        echo -e "${YELLOW}Docker is not installed or the Docker daemon is not reachable.${NC}"
        exit 1
    fi

    ensure_config_files
    load_proxy_env_from_dotenv

    echo "Building and starting PostgreSQL, frontend, gateway, and nginx..."
    cd "$DOCKER_DIR"
    "${COMPOSE[@]}" up --build -d --remove-orphans postgres frontend gateway nginx

    echo ""
    echo -e "${GREEN}DeerFlow Docker development environment is starting.${NC}"
    echo "Application: http://localhost:2026"
    echo "Logs:       make docker-logs"
    echo "Stop:       make docker-stop"
}

logs() {
    local service=""

    case "${1:-}" in
        --frontend) service="frontend" ;;
        --gateway) service="gateway" ;;
        --nginx) service="nginx" ;;
        --postgres) service="postgres" ;;
        "") ;;
        *)
            echo -e "${YELLOW}Unknown option: $1${NC}"
            echo "Usage: $0 logs [--frontend|--gateway|--nginx|--postgres]"
            exit 1
            ;;
    esac

    cd "$DOCKER_DIR"
    "${COMPOSE[@]}" logs -f $service
}

stop() {
    echo "Stopping Docker development services..."
    cd "$DOCKER_DIR"
    "${COMPOSE[@]}" down
    echo -e "${GREEN}Docker services stopped.${NC}"
}

restart() {
    echo "Restarting Docker development services..."
    cd "$DOCKER_DIR"
    "${COMPOSE[@]}" restart
    echo -e "${GREEN}Docker services restarted.${NC}"
    echo "Application: http://localhost:2026"
}

help() {
    echo "DeerFlow Docker Management Script"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  init              Check the Docker environment"
    echo "  start             Start the development services"
    echo "  restart           Restart the development services"
    echo "  logs [option]     Follow logs"
    echo "    --frontend      Frontend logs only"
    echo "    --gateway       Gateway logs only"
    echo "    --nginx         Nginx logs only"
    echo "    --postgres      PostgreSQL logs only"
    echo "  stop              Stop the development services"
    echo "  help              Show this help"
}

main() {
    case "${1:-}" in
        init) init ;;
        start) shift; start "$@" ;;
        restart) restart ;;
        logs) logs "${2:-}" ;;
        stop) stop ;;
        help|--help|-h|"") help ;;
        *)
            echo -e "${YELLOW}Unknown command: $1${NC}"
            echo ""
            help
            exit 1
            ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
