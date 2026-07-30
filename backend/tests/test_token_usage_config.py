'未说明'
from deerflow.config.token_usage_config import TokenUsageConfig


def test_token_usage_enabled_by_default():
    '未说明'
    assert TokenUsageConfig().enabled is True
