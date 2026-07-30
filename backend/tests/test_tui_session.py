'未说明'

from deerflow.tui.cli import LaunchPlan
from deerflow.tui.session import Session


class _Client:
    '未说明'
    def __init__(self, threads):
        '未说明'
        self._threads = threads

    def list_threads(self, limit=10):
        '未说明'
        return {"thread_list": self._threads}


def _session(threads):
    '未说明'
    return Session(client=_Client(threads))


THREADS = [
    {"thread_id": "thread-aaaa", "title": "Bug triage"},
    {"thread_id": "thread-bbbb", "title": "Write docs"},
]


def test_resolve_ref_matches_id():
    '未说明'
    assert _session(THREADS).resolve_ref("thread-bbbb") == "thread-bbbb"


def test_resolve_ref_matches_title():
    '未说明'
    assert _session(THREADS).resolve_ref("Bug triage") == "thread-aaaa"


def test_resolve_ref_unknown_falls_back_to_literal_id():
    '未说明'
    assert _session(THREADS).resolve_ref("brand-new-id") == "brand-new-id"


def test_resolve_thread_resolves_title_from_plan():
    '未说明'
    plan = LaunchPlan(mode="tui", thread_id="Write docs")
    assert _session(THREADS).resolve_thread(plan) == "thread-bbbb"


def test_resolve_thread_continue_returns_most_recent():
    '未说明'
    plan = LaunchPlan(mode="tui", continue_recent=True)
    assert _session(THREADS).resolve_thread(plan) == "thread-aaaa"


def test_close_is_a_noop_without_a_loop():
    # Headless sessions have no persistence loop; close() must be safe.
    '未说明'
    _session(THREADS).close()


def test_close_stops_the_background_loop():
    '未说明'
    from deerflow.tui.persistence import ThreadMetaWriter, _LoopThread

    loop = _LoopThread()
    session = Session(client=_Client(THREADS), writer=ThreadMetaWriter(loop, None), _loop=loop)
    session.close()
    assert session._loop is None
    session.close()  # idempotent
