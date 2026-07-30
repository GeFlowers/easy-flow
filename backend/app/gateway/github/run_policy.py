'定义 run_policy 模块提供的职责与可复用接口。\n\nPer-run policy hooks for the GitHub channel.\n\nThe generic ``ChannelManager`` looks up a :class:`ChannelRunPolicy`\nkeyed on ``msg.channel_name`` and applies it after ``_resolve_run_params``\nbut before the agent runs. The GitHub channel registers its policy\nentry from :func:`register_policy`, called once from the gateway\nbootstrap.\n\nKeeping the GitHub-specific provider closure here (rather than inline\nin ``ChannelManager``) lets every new webhook channel ship its own\n``run_policy.py`` with the same shape, with no edits to the manager.\n'

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.channels.message_bus import InboundMessage

logger = logging.getLogger(__name__)


async def inject_github_credentials(msg: InboundMessage, run_context: dict[str, Any]) -> None:
    '执行 inject_github_credentials 的明确职责，并返回与调用约定一致的结果。\n\nInstall a GitHub App installation token in ``run_context``.\n\n    The GitHub fan-out dispatcher carries each binding\'s\n    ``installation_id`` in ``msg.metadata["github"]``. We mint a\n    short-lived (1h) installation token and put the resulting **string**\n    into ``run_context["github_token"]``.\n\n    Why a string and not a closure:\n        ``run_context`` is passed to ``client.runs.wait(context=…)``\n        on the ``langgraph_sdk`` HTTP client, which JSON-encodes the\n        payload before sending it to Gateway\'s LangGraph-compatible\n        runtime over HTTP — even when that runtime is embedded in the\n        same process. A Python callable does not survive that\n        encoding (``TypeError: Type is not JSON serializable: function``).\n        The harness side (``_github_env_from_runtime`` in\n        ``packages/harness/deerflow/sandbox/tools.py``) already accepts\n        either a ``str`` or a zero-arg sync callable from\n        ``runtime.context["github_token"]``; only the ``str`` shape\n        round-trips through the SDK transport, so that is what we\n        ship.\n\n    Failure modes for autonomous runs that span past the 1h token TTL:\n        The minted token is valid for 1h. Most agent runs complete well\n        inside that window. Truly long coder runs (multi-hour refactors\n        on the higher ``recursion_limit=250`` ceiling) may see a 401 on\n        a late ``git push`` / ``gh pr create``. The fix for that —\n        re-installing a token-refresh hook on the **runtime side** by\n        pushing the ``installation_id`` through ``run_context`` and\n        looking up a process-local provider in the harness — is\n        deliberately deferred: it crosses the harness/app boundary\n        (``tests/test_harness_boundary.py``) and needs a registered\n        token-provider lookup, not a string-vs-closure switch.\n\n    Minting on the bus-consumer side (not in the webhook route) keeps\n    GitHub\'s 10s delivery timeout safe. Mint failures propagate up to\n    :meth:`ChannelManager._apply_channel_policy`, which logs and lets\n    the run proceed without credentials (read-only is better than no\n    response).\n    '
    if msg.channel_name != "github":
        return
    meta = msg.metadata if isinstance(msg.metadata, dict) else {}
    gh = meta.get("github")
    if not isinstance(gh, dict):
        return
    installation_id = gh.get("installation_id")
    if not isinstance(installation_id, int) or installation_id <= 0:
        return

    from app.gateway.github.app_auth import mint_installation_token

    # Mint and ship the token string. ``mint_installation_token`` caches
    # with a 5-min leeway, so subsequent runs against the same
    # installation reuse the cached token until ~55 min into its TTL.
    # Failures (bad App id, wrong installation_id, missing private key)
    # propagate to ``_apply_channel_policy``, which handles logging
    # without dropping the delivery.
    token = await mint_installation_token(installation_id)
    run_context["github_token"] = token
    logger.info(
        "[github-run-policy] installed installation token for installation_id=%s (TTL ~1h)",
        installation_id,
    )


def register_policy() -> None:
    "执行 register_policy 的明确职责，并返回与调用约定一致的结果。\n\nRegister the GitHub channel's :class:`ChannelRunPolicy` entry.\n\n    Called once from the gateway bootstrap so the manager finds the\n    policy on first delivery. Also invoked at module-import time below\n    so test code that constructs a :class:`ChannelManager` directly\n    (bypassing the gateway bootstrap) gets the same registration as\n    soon as anything inside ``app.gateway.github`` is imported.\n    Idempotent — registering twice just overwrites the same row.\n    "
    from app.channels.run_policy import CHANNEL_RUN_POLICY, ChannelRunPolicy

    CHANNEL_RUN_POLICY["github"] = ChannelRunPolicy(
        # GitHub webhooks have no synchronous human — ask_clarification
        # would dead-end the run.
        is_interactive=False,
        # Autonomous coder runs (clone -> edit -> test -> push -> PR)
        # routinely need more than the 100 super-step interactive ceiling.
        # Per-agent overrides via GitHubAgentConfig.recursion_limit still
        # win (read in ChannelManager._resolve_run_params from msg.metadata).
        default_recursion_limit=250,
        credentials_provider=inject_github_credentials,
        # GitHub deliveries are HMAC-authenticated at the webhook route,
        # and the binding from "sender" to DeerFlow user is encoded in
        # the agent's config.yaml ownership (not in the channel-connections
        # table). There is no per-sender /connect handshake — opting out
        # of the bound-identity gate is what lets webhook events reach
        # the agent even when channel_connections.enabled=True for
        # interactive IM channels in the same deployment.
        requires_bound_identity=False,
        # GitHub agents post their own outbound to the issue/PR via the
        # ``gh`` CLI in the sandbox; the channel's ``send`` is log-only
        # by design. We don't need to keep an HTTP stream open on
        # ``runs.wait`` for ~6-minute coding runs and then watch it die
        # at the SDK's 300s ``httpx.ReadTimeout``. Fire-and-forget swaps
        # the manager call to ``runs.create`` (returns immediately once
        # the run is ``pending``) and skips the response-extraction +
        # outbound-publish block. ``ConflictError`` on a busy thread is
        # still raised synchronously by ``start_run`` before the run is
        # accepted, so the busy-thread path is preserved.
        fire_and_forget=True,
    )


# Auto-register on import. Splitting CHANNEL_RUN_POLICY into
# ``app.channels.run_policy`` (not ``manager``) avoids the circular
# import that would otherwise arise: this module is imported via the
# github package, which the manager's shim methods reach into.
register_policy()
