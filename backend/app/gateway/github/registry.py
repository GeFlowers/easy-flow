"定义 registry 模块提供的职责与可复用接口。\n\nBuild the GitHub webhook → agent registry.\n\nWalks every user's custom-agent directory under ``{base_dir}/users/`` plus\nthe legacy shared layout at ``{base_dir}/agents/`` and indexes every agent\nthat declares a ``github:`` block by the ``(repo, event)`` pairs it\ndeclares an interest in.\n\nThe dispatcher calls :func:`build_github_agent_registry` once per webhook\ndelivery. We avoid re-parsing every ``config.yaml`` on each call via a\nsmall mtime-keyed cache: the directory listing + ``stat()`` per config\nfile is cheap (~µs), while ``yaml.safe_load`` is the dominant cost\n(~hundreds of µs per file). The cache key is the sorted tuple of\n``(user_id, agent_name, config.yaml mtime)`` triples; any mtime change,\naddition, or deletion invalidates the cache transparently. Operators\nwho hand-edit ``config.yaml`` see the change on the next webhook.\n\nCache invalidation caveat: mtime granularity on macOS HFS+ / APFS is\n~1 µs but on some filesystems (FAT, network shares with caching) it's\n1 s. Two edits inside the same coarse-tick would look identical. For\nthe dispatch path that's fine — webhooks are rare relative to operator\nedits, and the next non-coincident write reconciles. If we ever land\noperator tooling that batches sub-second edits, we can extend the\nsignature with file size or a content hash.\n"

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from app.gateway.github.triggers import _resolved_trigger
from deerflow.config.agents_config import (
    AgentConfig,
    GitHubTriggerConfig,
    load_agent_config,
)
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import DEFAULT_USER_ID

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitHubAgentMatch:
    '封装 GitHubAgentMatch 的状态、协作关系与公开操作。\n\nOne ``(user, agent, _resolved_trigger)`` row in the ``(repo, event)`` index.\n\n    The trigger is the binding override merged with per-event field defaults\n    (see :func:`app.gateway.github.triggers._resolved_trigger`), so the\n    dispatcher does not have to re-resolve it at fan-out time. Pre-resolving\n    here also folds the per-binding lookup out of the hot path: the registry\n    already chose the right binding for this ``(repo, event)``, so the\n    dispatcher\'s old "find the binding whose ``.repo`` matches" loop —\n    which silently dropped events when an agent had multiple bindings on\n    one repo (PR feedback R3) — disappears entirely. Single-binding-per-repo\n    is enforced upstream by :class:`GitHubAgentConfig`\'s validator, so\n    each ``(repo, event)`` resolves to exactly one trigger per agent.\n\n    The ``github:`` block is read off ``agent.github`` (always non-None\n    here — the rebuild filters agents without one before constructing a\n    match), so we don\'t carry a separate ``github`` field.\n    '

    user_id: str
    agent: AgentConfig
    trigger: GitHubTriggerConfig


# Cache: (signature, registry). ``signature`` is a tuple of
# ``(user_id, agent_name, mtime)`` triples. Identical signature → registry
# is still valid, skip the YAML parses.
_Signature = tuple[tuple[str, str, float], ...]
_Registry = dict[tuple[str, str], list[GitHubAgentMatch]]
_cache: tuple[_Signature, _Registry] | None = None
# Threading lock (not asyncio): build_github_agent_registry is invoked
# from asyncio.to_thread in the dispatcher, so the lock is acquired on
# the worker thread. A plain Lock is the right primitive here.
_cache_lock = threading.Lock()


def _discover_user_ids() -> list[str]:
    '执行 _discover_user_ids 的明确职责，并返回与调用约定一致的结果。\n\nReturn all user-id directories under ``base_dir/users/``.\n\n    Falls back to ``[DEFAULT_USER_ID]`` so the no-auth dev setup (which\n    keeps everything in ``users/default/``) is always covered even before\n    the directory has been created on disk.\n    '
    paths = get_paths()
    users_dir: Path = paths.base_dir / "users"
    if not users_dir.exists():
        return [DEFAULT_USER_ID]

    found: list[str] = []
    for entry in sorted(users_dir.iterdir()):
        if entry.is_dir() and (entry / "agents").exists():
            found.append(entry.name)
    if DEFAULT_USER_ID not in found:
        found.append(DEFAULT_USER_ID)
    return found


def _gather_agent_signature() -> tuple[_Signature, list[tuple[str, str]]]:
    "执行 _gather_agent_signature 的明确职责，并返回与调用约定一致的结果。\n\nReturn (signature, [(user_id, agent_name)]) for every agent on disk.\n\n    The signature lets us skip the YAML parse on warm hits; the\n    discovered list lets the rebuilder process exactly the agents that\n    the signature covers. Doing iterdir + stat is cheap (~µs each); the\n    full cost we avoid is the ``yaml.safe_load`` per config.\n\n    Includes the legacy shared layout at ``{base_dir}/agents/`` under the\n    :data:`DEFAULT_USER_ID` bucket so unmigrated installations still\n    receive webhook fan-out. Per-user entries shadow legacy entries with\n    the same name (matching :func:`list_custom_agents`' precedence), so\n    once an install runs ``migrate_user_isolation.py`` the legacy entry\n    is silently superseded rather than producing duplicate rows.\n    "
    paths = get_paths()
    sig: list[tuple[str, str, float]] = []
    discovered: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for user_id in _discover_user_ids():
        agent_root = paths.user_agents_dir(user_id)
        if not agent_root.exists():
            continue
        for entry in sorted(agent_root.iterdir()):
            config = entry / "config.yaml"
            if not entry.is_dir() or not config.exists():
                continue
            try:
                mtime = config.stat().st_mtime
            except OSError:
                # Vanished between iterdir and stat — racing operator
                # edit. Drop from this round; next call picks it up.
                continue
            sig.append((user_id, entry.name, mtime))
            discovered.append((user_id, entry.name))
            seen.add((user_id, entry.name))

    # Legacy shared layout: {base_dir}/agents/{name}/. CLAUDE.md commits
    # to this as a read-only fallback for unmigrated installs, and
    # load_agent_config() / list_custom_agents() honour it — the webhook
    # path must too, or an unmigrated install with a ``github:`` block on
    # a shared agent silently fans out to nothing. Legacy entries map
    # onto the DEFAULT_USER_ID bucket because that is the user-id
    # ``load_agent_config(name)`` resolves them under at run-time.
    legacy_root = paths.agents_dir
    if legacy_root.exists():
        for entry in sorted(legacy_root.iterdir()):
            config = entry / "config.yaml"
            if not entry.is_dir() or not config.exists():
                continue
            # Per-user shadow: if users/default/agents/{name} already
            # exists, skip the legacy entry so we don't index the same
            # agent twice with conflicting trigger sets.
            if (DEFAULT_USER_ID, entry.name) in seen:
                continue
            try:
                mtime = config.stat().st_mtime
            except OSError:
                continue
            sig.append((DEFAULT_USER_ID, entry.name, mtime))
            discovered.append((DEFAULT_USER_ID, entry.name))
            seen.add((DEFAULT_USER_ID, entry.name))
    return tuple(sig), discovered


def _rebuild(discovered: list[tuple[str, str]]) -> _Registry:
    "执行 _rebuild 的明确职责，并返回与调用约定一致的结果。\n\nParse every agent's config.yaml and build the (repo, event) index.\n\n    Each ``(repo, event)`` slot stores :class:`GitHubAgentMatch` rows — the\n    user_id + AgentConfig + the trigger already resolved (binding override\n    merged with per-event field defaults). The dispatcher then only needs\n    to apply the trigger; it never re-walks ``bindings`` to find the right\n    one. Single-binding-per-repo is enforced by\n    :class:`GitHubAgentConfig`'s validator, so a duplicate-repo config\n    fails to load here (logged as a skip) instead of producing duplicate\n    rows in this index.\n    "
    index: _Registry = {}
    for user_id, agent_name in discovered:
        try:
            cfg = load_agent_config(agent_name, user_id=user_id)
        except Exception as exc:  # noqa: BLE001 — one bad agent must not kill the scan
            logger.warning("github_registry: skipping agent %s/%s: %s", user_id, agent_name, exc)
            continue
        if cfg is None or cfg.github is None:
            continue
        for binding in cfg.github.bindings:
            for event, override in binding.triggers.items():
                resolved = _resolved_trigger(event, {event: override})
                if resolved is None:
                    # ``_resolved_trigger`` only returns None when the
                    # event is not in the dict we passed — by construction
                    # it is here, so this branch is unreachable. Keep the
                    # guard for type-checker happiness.
                    continue
                index.setdefault((binding.repo, event), []).append(GitHubAgentMatch(user_id=user_id, agent=cfg, trigger=resolved))
    return index


def build_github_agent_registry() -> _Registry:
    '构建并返回，并遵守 build_github_agent_registry 所表达的接口约束。\n\nReturn ``{(repo, event): [GitHubAgentMatch, ...]}`` across all users.\n\n    Each agent appears in the index once per ``(repo, declared_event)`` pair,\n    with the per-event trigger pre-resolved by merging the binding override\n    with :data:`app.gateway.github.triggers.DEFAULT_TRIGGERS`. Events are\n    opt-in per binding: an agent only registers for the events it explicitly\n    lists under ``github.bindings[].triggers``. An agent that declares an\n    empty ``triggers:`` map (or omits it) registers for nothing and the\n    dispatcher will never fan a webhook out to it.\n\n    Warm path (no agents added/removed/edited since the last call) costs\n    only the iterdir + stat pass — no YAML parsing. Cold path parses\n    every config.yaml and refreshes the cache. The result is shared\n    across callers (returned by reference) since :class:`GitHubAgentMatch`\n    is frozen and the registry is intended as read-only.\n    '
    global _cache
    with _cache_lock:
        signature, discovered = _gather_agent_signature()
        if _cache is not None and _cache[0] == signature:
            return _cache[1]
        registry = _rebuild(discovered)
        _cache = (signature, registry)
        return registry


def _invalidate_cache() -> None:
    '执行 _invalidate_cache 的明确职责，并返回与调用约定一致的结果。\n\nDrop the cached registry. Test-only helper.'
    global _cache
    with _cache_lock:
        _cache = None


def lookup_agents(
    registry: _Registry,
    repo: str,
    event: str,
) -> list[GitHubAgentMatch]:
    "执行 lookup_agents 的明确职责，并返回与调用约定一致的结果。\n\nConvenience: return the list of agent matches for ``(repo, event)``.\n\n    Each match carries the user, AgentConfig (with ``.github`` attached),\n    and the pre-resolved trigger config for this specific event, so the\n    caller does not need to walk the agent's ``bindings`` again.\n    "
    return registry.get((repo, event), [])
