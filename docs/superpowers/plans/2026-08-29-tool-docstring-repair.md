# Tool Docstring Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore every LangChain-parsed tool docstring so the Gateway imports and starts, with a regression test that catches the whole class of failure.

**Architecture:** Add an AST-based test that discovers every backend `@tool(..., parse_docstring=True)` function without importing the broken tool package, then validates the docstring through LangChain's parser and checks descriptions for every model-facing parameter. Restore only the affected docstrings and nearby corrupted placeholder comments, retaining current function bodies and signatures.

**Tech Stack:** Python 3.12, pytest, Python `ast`, LangChain Core 1.3.3, Ruff, FastAPI/Gateway, Docker Compose development stack.

**Spec:** `docs/superpowers/specs/2026-08-29-tool-docstring-repair.md`

## Global Constraints

- Keep every existing `parse_docstring=True` setting.
- All parameter names in `Args:` must match the current function signature.
- Do not expose or commit the VectorEngine API key.
- Preserve local configuration and `LOCAL_SETUP_SUMMARY.md`.
- Backend fixes require tests plus synchronized `README.md` and `backend/AGENTS.md` documentation.

---

### Task 1: Repository-wide docstring contract test

**Files:**
- Create: `backend/tests/test_tool_docstring_contract.py`

**Interfaces:**
- Consumes: repository-owned Python source under `backend/app`, `backend/packages`, `backend/scripts`, and `backend/tests`, plus LangChain's Google-docstring parser.
- Produces: one pytest contract that lists every invalid decorated tool and missing model-facing parameter description.

- [x] **Step 1: Write the failing test**

  Create the test with this discovery and validation shape:

  ```python
  def test_parse_docstring_tools_have_valid_google_docstrings() -> None:
      findings: list[str] = []
      discovered = 0
      for source_root in SOURCE_ROOTS:
          for source_path in source_root.rglob("*.py"):
              tree = ast.parse(source_path.read_text(encoding="utf-8"))
              for function in _parse_docstring_functions(tree):
              discovered += 1
              argument_names = _argument_names(function)
              try:
                  _, descriptions = _parse_google_docstring(
                      ast.get_docstring(function, clean=True),
                      argument_names,
                      error_on_invalid_docstring=True,
                  )
              except ValueError as exc:
                  findings.append(f"{source_path}:{function.lineno}: {function.name}: {exc}")
                  continue
              missing = [
                  name
                  for name in argument_names
                  if name not in INJECTED_ARGUMENT_NAMES and not descriptions.get(name)
              ]
              if missing:
                  findings.append(f"{source_path}:{function.lineno}: {function.name}: missing {missing}")
      assert discovered > 0
      assert findings == []
  ```

- [x] **Step 2: Run test to verify it fails**

  Run: `uv run pytest tests/test_tool_docstring_contract.py -v`

  Expected: one assertion failure listing the 41 malformed tools, including
  `ask_clarification_tool`; the test itself must collect successfully.

- [x] **Step 3: Keep the test unchanged for the implementation phase**

  The production change that makes it pass must be valid docstrings, not a
  weaker assertion or a parser bypass.

### Task 2: Restore built-in, sandbox, memory, and management tool descriptions

**Files:**
- Modify: `backend/packages/harness/deerflow/sandbox/tools.py`
- Modify: `backend/packages/harness/deerflow/agents/memory/tools.py`
- Modify: `backend/packages/harness/deerflow/tools/skill_manage_tool.py`
- Modify: `backend/packages/harness/deerflow/tools/builtins/clarification_tool.py`
- Modify: `backend/packages/harness/deerflow/tools/builtins/present_file_tool.py`
- Modify: `backend/packages/harness/deerflow/tools/builtins/review_skill_package_tool.py`
- Modify: `backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py`
- Modify: `backend/packages/harness/deerflow/tools/builtins/view_image_tool.py`

**Interfaces:**
- Consumes: current signatures and historical docstrings from `68dfcd322^`.
- Produces: valid model-facing descriptions for all affected core tools.

- [x] **Step 1: Restore Google-style docstrings**

  Preserve the current short summary where useful, restore operational guidance,
  add a blank line followed by `Args:`, and document every current non-injected
  parameter by its exact name.

- [x] **Step 2: Remove adjacent meaningless placeholder comments**

  Delete repeated `# 中文说明：此处用于执行相关处理。` lines in the touched
  tool definitions while retaining real explanatory comments.

- [x] **Step 3: Run the contract test**

  Run: `uv run pytest tests/test_tool_docstring_contract.py -v`

  Expected: failures remain only in community provider tools.

### Task 3: Restore community provider tool descriptions

**Files:**
- Modify: affected `tools.py` files under `backend/packages/harness/deerflow/community/` for Brave, Browserless, Crawl4AI, DuckDuckGo, Exa, FastCRW, Firecrawl, GroundRoute, image search, InfoQuest, Jina AI, SearXNG, Serper, and Tavily.

**Interfaces:**
- Consumes: current provider signatures and their pre-`68dfcd322` descriptions.
- Produces: valid schemas for every configured search, fetch, capture, and image-search provider.

- [x] **Step 1: Restore each provider docstring**

  Use real multiline strings, preserve URL-safety and usage guidance, and add an
  exact `Args:` entry for every current model-facing parameter.

- [x] **Step 2: Run the contract test**

  Run: `uv run pytest tests/test_tool_docstring_contract.py -v`

  Expected: pass with all 45 discovered production tools and test fixtures valid.

- [x] **Step 3: Run the existing tool-schema regression test**

  Run: `uv run pytest tests/test_tool_args_schema_no_pydantic_warning.py -v`

  Expected: collection succeeds and all cases pass without missing-description warnings.

### Task 4: Documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `backend/AGENTS.md`

**Interfaces:**
- Consumes: the final test contract and repair approach.
- Produces: developer guidance that model-facing docstrings are runtime schema and must retain Google-style `Args:` blocks.

- [x] **Step 1: Update documentation**

  Add a concise maintenance note explaining the contract and name the regression
  test developers should run after editing tool descriptions.

- [x] **Step 2: Run focused verification**

  Run the new contract test, existing schema test, clarification middleware tests,
  and `uv run python -c "from app.gateway.app import app"`.

- [x] **Step 3: Run formatting, lint, and backend tests**

  Run Ruff formatting/checks on changed Python files, then run the backend test
  suite. Record any unrelated environmental failures separately.

  Verification record: the new scanner and focused changed behavior pass Ruff
  and pytest. The inherited mass-localization baseline still has unrelated Ruff
  failures (including escaped single-line docstrings outside this repair) and
  Windows-only POSIX test failures; the Linux Docker run passed 7611 tests with
  only missing retired docs and a missing `git` executable in the test image.

- [ ] **Step 4: Verify Docker behavior after integration**

  Restart or rebuild the Gateway in the main configured workspace, inspect its
  logs, and request `http://localhost:2026/api/models`; confirm that the original
  docstring exception and API 502 are gone.
