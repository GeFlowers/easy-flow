# 在 Git Bash 中使用。
.PHONY: help start stop

help:
	@echo "make start: 启动项目；make stop: 关闭项目"

start:
	bash scripts/start.sh

stop:
	bash scripts/stop.sh
