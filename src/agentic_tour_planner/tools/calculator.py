from __future__ import annotations

import re
from typing import Any

from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}"


class Calculator:
    """Safe arithmetic evaluator that records each reduction step for transparency."""

    def evaluate(self, expression: str) -> tuple[float, list[str]]:
        logger.debug(f"evaluate called with expression={expression!r}")
        tokens = self._tokenize(expression)
        value, steps, _ = self._parse_expr(tokens, 0)
        logger.debug(f"evaluate result={value} in {len(steps)} step(s)")
        return value, steps

    @staticmethod
    def _tokenize(expression: str) -> list[str]:
        expression = expression.replace("{", "(").replace("}", ")")
        tokens: list[str] = []
        for match in re.finditer(r"\d+\.?\d*|[()+\-*/]", expression.replace(" ", "")):
            tokens.append(match.group())
        return tokens

    def _parse_expr(self, tokens: list[str], i: int) -> tuple[float, list[str], int]:
        value, steps, i = self._parse_term(tokens, i)
        while i < len(tokens) and tokens[i] in ("+", "-"):
            op = tokens[i]
            i += 1
            rhs, rhs_steps, i = self._parse_term(tokens, i)
            new_value = value + rhs if op == "+" else value - rhs
            steps.extend(rhs_steps)
            steps.append(f"{_fmt(value)} {op} {_fmt(rhs)} = {_fmt(new_value)}")
            value = new_value
        return value, steps, i

    def _parse_term(self, tokens: list[str], i: int) -> tuple[float, list[str], int]:
        value, steps, i = self._parse_factor(tokens, i)
        while i < len(tokens) and tokens[i] in ("*", "/"):
            op = tokens[i]
            i += 1
            rhs, rhs_steps, i = self._parse_factor(tokens, i)
            steps.extend(rhs_steps)
            if op == "*":
                new_value = value * rhs
                steps.append(f"{_fmt(value)} * {_fmt(rhs)} = {_fmt(new_value)}")
            else:
                new_value = value / rhs
                steps.append(f"{_fmt(value)} / {_fmt(rhs)} = {_fmt(new_value)}")
            value = new_value
        return value, steps, i

    def _parse_factor(self, tokens: list[str], i: int) -> tuple[float, list[str], int]:
        if i < len(tokens) and tokens[i] == "(":
            i += 1
            value, steps, i = self._parse_expr(tokens, i)
            if i < len(tokens) and tokens[i] == ")":
                i += 1
            return value, steps, i
        number = float(tokens[i])
        i += 1
        return number, [], i


def run_calculator(args: dict[str, Any]) -> dict[str, Any]:
    """Tool entry point: evaluate an arithmetic expression with step logging."""
    expression = str(args.get("expression", "")).strip()
    label = str(args.get("label", expression))
    logger.debug(f"run_calculator called with expression={expression!r} label={label!r}")
    try:
        value, steps = Calculator().evaluate(expression)
        result = round(value, 2)
        logger.debug(f"run_calculator succeeded: {expression!r} = {result}")
        return {
            "label": label,
            "expression": expression,
            "result": result,
            "steps": steps,
        }
    except Exception as exc:
        logger.warning(f"run_calculator failed for {expression!r}: {exc}")
        return {"label": label, "expression": expression, "error": str(exc)}


CALCULATOR_TOOL = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": (
            "Evaluate an arithmetic cost expression (supports + - * / and parentheses). "
            "Call it for every subtotal and the grand total so the math is shown step by step. "
            "Example: calculator(expression='120 * 4 + 30 * 4', label='Day 1 total for 4 people')"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Arithmetic expression, e.g. '120 * 4 + 30 * 4'.",
                },
                "label": {
                    "type": "string",
                    "description": "Short human-readable label for this calculation.",
                },
            },
            "required": ["expression"],
        },
    },
}
