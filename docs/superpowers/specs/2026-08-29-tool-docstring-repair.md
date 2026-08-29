# Tool Docstring Repair Specification

## Problem

Gateway startup fails while importing `ask_clarification_tool` because LangChain
Core 1.3.3 rejects its malformed Google-style docstring. A repository-wide
static audit found 41 invalid functions among the 43 tools decorated with
`parse_docstring=True`. Before commit `68dfcd322`, all 43 parsed successfully.

## Required outcome

- Every backend Python tool or test fixture decorated with
  `parse_docstring=True` has a valid
  Google-style docstring.
- Every model-facing parameter has a non-empty description in the generated
  tool schema.
- Runtime-injected parameters such as `runtime` and `tool_call_id` may be
  omitted from the model-facing schema, but their presence must not make the
  parser reject the docstring.
- Gateway modules import without a docstring parser exception.
- A static regression test reports all malformed backend tools in one failure instead
  of stopping at the first import-time error.
- Existing behavior outside tool descriptions remains unchanged.

## Constraints

- Keep `parse_docstring=True`; disabling schema parsing is not an acceptable
  workaround.
- Use the pre-`68dfcd322` descriptions as semantic reference, reconciled with
  current function signatures.
- Do not revert the complete mass-localization commit.
- Preserve local configuration, secrets, and `LOCAL_SETUP_SUMMARY.md`.
- Follow backend TDD, formatting, testing, and documentation requirements.
