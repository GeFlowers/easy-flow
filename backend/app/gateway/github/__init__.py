'定义 __init__ 模块提供的职责与可复用接口。\n\nGitHub webhook dispatcher subpackage.\n\nSplits the inbound-webhook → custom-agent → write-back pipeline into small,\nsingle-purpose modules so each piece can be tested in isolation:\n\n* :mod:`identity` — bot-loop prevention and deterministic thread ids.\n* :mod:`triggers` — pure logic deciding whether an event fires an agent.\n* :mod:`prompts` — payload → user prompt strings.\n* :mod:`registry` — scan custom agents and index them by (repo, event).\n* :mod:`app_auth` — GitHub App JWT and installation-token minting.\n* :mod:`writeback` — POST comments back to GitHub.\n* :mod:`run_policy` — ChannelRunPolicy entry registered into ChannelManager.\n* :mod:`dispatcher` — orchestrates all of the above and creates a langgraph run.\n\nThe router in :mod:`app.gateway.routers.github_webhooks` is the only consumer\nof this package.\n'

# Side-effect import: registers the GitHub channel's ChannelRunPolicy
# (non-interactive flag, recursion_limit bump, installation-token
# provider) so the manager finds it on first delivery — and tests that
# build a ChannelManager directly inherit the registration as soon as
# anything inside this subpackage is imported.
from app.gateway.github import run_policy  # noqa: F401
