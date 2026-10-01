'''支持通过 python -m deerflow.tui 启动终端界面。'''

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
