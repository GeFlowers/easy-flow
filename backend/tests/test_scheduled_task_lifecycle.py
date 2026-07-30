'未说明'
from app.gateway.app import create_app


def test_gateway_app_includes_scheduled_task_router():
    '未说明'
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/scheduled-tasks" in paths
