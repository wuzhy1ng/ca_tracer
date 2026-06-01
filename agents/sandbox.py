from __future__ import annotations

import ast
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from algos import baseline


class SandboxError(RuntimeError):
    pass


@dataclass
class SandboxResult:
    name: str
    function: Callable
    source: str


FORBIDDEN_NAMES = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "globals",
    "locals",
    "open",
    "input",
    "breakpoint",
}

ALLOWED_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}

ALLOWED_GLOBALS = {
    "Decimal": Decimal,
    "MatchResult": baseline.MatchResult,
    "event_amount": baseline.event_amount,
    "event_time": baseline.event_time,
    "amount_gap": baseline.amount_gap,
    "time_gap_hours": baseline.time_gap_hours,
    "make_result": baseline.make_result,
    "is_round_amount": baseline.is_round_amount,
}


def _validate_ast(tree: ast.Module) -> str:
    function_defs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(function_defs) != 1 or len(tree.body) != 1:
        raise SandboxError("source must contain exactly one top-level function definition")
    function_name = function_defs[0].name
    if function_name.startswith("_"):
        raise SandboxError("function name must not be private")

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.ClassDef)):
            raise SandboxError(f"forbidden syntax: {type(node).__name__}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise SandboxError("dunder attribute access is forbidden")
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise SandboxError(f"forbidden name: {node.id}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_NAMES:
            raise SandboxError(f"forbidden call: {node.func.id}")
    return function_name


def load_operator_from_source(source: str) -> SandboxResult:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SandboxError(f"syntax error: {exc}") from exc
    function_name = _validate_ast(tree)
    code = compile(tree, "<generated_operator>", "exec")
    env = {"__builtins__": ALLOWED_BUILTINS, **ALLOWED_GLOBALS}
    namespace: dict = {}
    exec(code, env, namespace)
    fn = namespace.get(function_name)
    if not callable(fn):
        raise SandboxError("generated function was not callable")
    return SandboxResult(name=function_name, function=fn, source=source)
