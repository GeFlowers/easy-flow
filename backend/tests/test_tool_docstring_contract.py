from __future__ import annotations

import ast
from pathlib import Path

import pytest
from langchain_core.utils.function_calling import _parse_google_docstring

BACKEND_ROOT = Path(__file__).parents[1]
SOURCE_ROOTS = tuple(BACKEND_ROOT / name for name in ("app", "packages", "scripts", "tests"))
TOOL_MODULES = {"langchain.tools", "langchain_core.tools"}
INJECTED_TYPE_IMPORTS = {
    "deerflow.tools.types": {"Runtime"},
    "langchain.tools": {"InjectedState", "InjectedStore", "InjectedToolArg", "InjectedToolCallId", "ToolRuntime"},
    "langchain_core.tools": {"InjectedState", "InjectedStore", "InjectedToolArg", "InjectedToolCallId", "ToolRuntime"},
    "langgraph.prebuilt": {"InjectedState", "InjectedStore"},
}


def _attribute_path(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attribute_path(node.value)
        if parent:
            return f"{parent}.{node.attr}"
    return None


def _tool_decorator_references(tree: ast.AST) -> set[str]:
    references: set[str] = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.ImportFrom) and node.module in TOOL_MODULES:
            references.update(alias.asname or alias.name for alias in node.names if alias.name == "tool")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in TOOL_MODULES:
                    references.add(f"{alias.asname or alias.name}.tool")
    return references


def _parse_docstring_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    tool_references = _tool_decorator_references(tree)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or _attribute_path(decorator.func) not in tool_references:
                continue
            if any(keyword.arg is None for keyword in decorator.keywords):
                raise ValueError(f"{node.name}: @tool keyword expansion is unsupported; use literal parse_docstring=True/False")
            parse_keywords = [keyword for keyword in decorator.keywords if keyword.arg == "parse_docstring"]
            if not parse_keywords:
                continue
            value = parse_keywords[-1].value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, bool):
                raise ValueError(f"{node.name}: @tool parse_docstring must be a literal boolean")
            if value.value:
                functions.append(node)
    return functions


def _argument_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    arguments = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
    return [argument.arg for argument in arguments if argument.arg not in {"self", "cls"}]


def _injected_type_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.ImportFrom):
            allowed_names = INJECTED_TYPE_IMPORTS.get(node.module or "", set())
            names.update(alias.asname or alias.name for alias in node.names if alias.name in allowed_names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                allowed_names = INJECTED_TYPE_IMPORTS.get(alias.name, set())
                prefix = alias.asname or alias.name
                names.update(f"{prefix}.{type_name}" for type_name in allowed_names)
    return names


def _is_injected_argument(argument: ast.arg, injected_type_names: set[str]) -> bool:
    if argument.annotation is None:
        return False
    return any((reference := _attribute_path(node)) is not None and reference in injected_type_names for node in ast.walk(argument.annotation) if isinstance(node, (ast.Name, ast.Attribute)))


def test_discovery_ignores_unrelated_decorators_with_parse_docstring_keyword() -> None:
    tree = ast.parse(
        """
@unrelated(parse_docstring=True)
def sample(value: str) -> str:
    return value
"""
    )

    assert _parse_docstring_functions(tree) == []


@pytest.mark.parametrize(
    "source",
    [
        """
from langchain.tools import tool as lc_tool

@lc_tool(parse_docstring=True)
def sample(value: str) -> str:
    return value
""",
        """
import langchain.tools as lc_tools

@lc_tools.tool(parse_docstring=True)
def sample(value: str) -> str:
    return value
""",
    ],
)
def test_discovery_recognizes_imported_tool_aliases(source: str) -> None:
    functions = _parse_docstring_functions(ast.parse(source))

    assert [function.name for function in functions] == ["sample"]


def test_discovery_rejects_dynamic_parse_docstring_configuration() -> None:
    tree = ast.parse(
        """
from langchain.tools import tool

PARSE_DOCSTRINGS = True

@tool(parse_docstring=PARSE_DOCSTRINGS)
def sample(value: str) -> str:
    return value
"""
    )

    with pytest.raises(ValueError, match="literal boolean"):
        _parse_docstring_functions(tree)


def test_injected_arguments_are_identified_by_imported_annotation_not_name() -> None:
    tree = ast.parse(
        """
from typing import Annotated
from deerflow.tools.types import Runtime
from langchain_core.tools import InjectedToolCallId

def sample(runtime: str, actual_runtime: Runtime, tool_call_id: Annotated[str, InjectedToolCallId]) -> None:
    pass
"""
    )
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))
    injected_type_names = _injected_type_names(tree)

    assert _is_injected_argument(function.args.args[0], injected_type_names) is False
    assert _is_injected_argument(function.args.args[1], injected_type_names) is True
    assert _is_injected_argument(function.args.args[2], injected_type_names) is True


def test_parse_docstring_tools_have_valid_google_docstrings() -> None:
    findings: list[str] = []
    discovered = 0

    for source_root in SOURCE_ROOTS:
        for source_path in source_root.rglob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            injected_type_names = _injected_type_names(tree)
            try:
                functions = _parse_docstring_functions(tree)
            except ValueError as exc:
                findings.append(f"{source_path.relative_to(BACKEND_ROOT)}: {exc}")
                continue
            for function in functions:
                discovered += 1
                argument_names = _argument_names(function)
                try:
                    _, descriptions = _parse_google_docstring(
                        ast.get_docstring(function, clean=True),
                        argument_names,
                        error_on_invalid_docstring=True,
                    )
                except ValueError as exc:
                    findings.append(f"{source_path.relative_to(BACKEND_ROOT)}:{function.lineno}: {function.name}: {exc}")
                    continue

                arguments = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
                missing_descriptions = [argument.arg for argument in arguments if argument.arg not in {"self", "cls"} and not _is_injected_argument(argument, injected_type_names) and not descriptions.get(argument.arg)]
                if missing_descriptions:
                    findings.append(f"{source_path.relative_to(BACKEND_ROOT)}:{function.lineno}: {function.name}: missing descriptions for {missing_descriptions}")

    assert discovered > 0, f"No parse_docstring=True tools found under {BACKEND_ROOT}"
    assert findings == [], "Invalid model-facing tool docstrings:\n" + "\n".join(findings)
