# Blocking I/O regression tests

The backend keeps focused regression tests for known blocking-I/O risks on the
async event loop. This repository no longer includes a static source scanner.

The tests use Blockbuster to protect selected production paths from synchronous
I/O blocking the asyncio event loop.

## Run the regression tests

The CI regression gate uses Blockbuster to fail when covered code under `app.*`
or `deerflow.*` performs blocking I/O on the asyncio event-loop thread.

Run it from `backend/`:

```bash
make test-blocking-io
```

The runtime gate starts from confirmed production bugs and protects those
paths from regressing. It does not prove that the entire backend is free of
blocking IO; it only covers the production paths exercised by
`backend/tests/blocking_io/`.

## Maintenance

When a high-risk async production path is identified during development or
review, add a focused runtime anchor so CI can prevent it from regressing.
Runtime detection has two maintenance paths.

### Add a runtime rule

Add a runtime rule when Blockbuster's default rules do not cover a generic
blocking primitive used by production code.

Rules belong in:

```text
backend/tests/support/detectors/blocking_io_runtime.py
```

Add them to `_PROJECT_BLOCKING_RULES`, not directly inside individual tests.
Keeping rules centralized makes it clear which extra primitives DeerFlow
expects Blockbuster to catch.

Example shape:

```python
import subprocess

from blockbuster import BlockBusterFunction

_PROJECT_BLOCKING_RULES = (
    (
        "subprocess.Popen.__init__",
        BlockBusterFunction(
            subprocess.Popen,
            "__init__",
            scanned_modules=["app", "deerflow"],
        ),
    ),
)
```

Do not add a runtime rule just because a business path is not tested. A rule
only expands what Blockbuster can intercept after code runs.

### Add a runtime anchor

Add a runtime anchor when a high-risk async production path should be protected
by CI but no existing `backend/tests/blocking_io/` test executes it.

Anchors belong in:

```text
backend/tests/blocking_io/
```

A good anchor should:

- Call the real production async entry point.
- Avoid bypassing the blocking surface with test-only `asyncio.to_thread`
  wrappers.
- Use real local filesystem inputs when the bug shape is filesystem IO.
- Mock only the external dependency boundary, such as a network service or
  third-party saver class.
- Fail if a future change moves the blocking operation back onto the event
  loop.

Avoid testing only the low-level helper unless that helper is the production
async entry point. The runtime gate is most useful when it protects the caller
that production actually executes.

## Current runtime coverage

The runtime anchors protect confirmed blocking-IO bug shapes:

- PostgreSQL checkpointer setup through the async persistence lifecycle.
- Subagent skill metadata loading through `SubagentExecutor._load_skills()`.
- `JsonlRunEventStore` async API (`put` / `list_*` / `delete_*`): the JSONL
  run-event backend offloads its synchronous file IO via `asyncio.to_thread`
  (fix #3084); this anchor drives the real async API under the gate so any
  blocking IO reintroduced on the loop fails, not only removal of one
  `to_thread` call.
- `UploadsMiddleware.before_agent` uploads-directory scan: a sync-only middleware
  hook runs on the event loop under async graph execution, so the scan is
  offloaded via `abefore_agent` + `run_in_executor`.
- Gate health checks: Blockbuster catches unoffloaded calls, opt-out works, and
  patches are restored after exceptions.

As review identifies more high-risk async paths, add runtime anchors
incrementally.
