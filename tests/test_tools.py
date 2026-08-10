"""Tests for agent tools — especially calculator safety (no code execution)."""

import pytest

from src.resilience.node_gate import PREFIX_TOOL_ERROR
from src.tools.all_tools import calculator, safe_calculate


def test_calculator_basic_arithmetic():
    assert calculator.invoke({"expression": "847 * 293"}) == "248171"
    assert calculator.invoke({"expression": "(100 + 50) / 3"}) == "50.0"
    assert calculator.invoke({"expression": "2 ** 10"}) == "1024"
    assert calculator.invoke({"expression": "-5 + 3"}) == "-2"


def test_calculator_rejects_code_execution():
    """The calculator must never execute arbitrary code (prompt injection → RCE)."""
    dangerous = [
        "__import__('os').system('id')",
        "open('/etc/passwd').read()",
        "exec('print(1)')",
        "().__class__.__mro__",
        "[x for x in (1,)]",
        "'a' * 10",
    ]
    for expr in dangerous:
        result = calculator.invoke({"expression": expr})
        assert result.startswith(PREFIX_TOOL_ERROR), (
            f"Expression was not rejected: {expr}"
        )


def test_safe_calculate_rejects_huge_exponents():
    with pytest.raises(ValueError):
        safe_calculate("9 ** 999999")


def test_safe_calculate_rejects_long_expressions():
    with pytest.raises(ValueError):
        safe_calculate("1+" * 200 + "1")


def test_calculator_handles_division_by_zero():
    result = calculator.invoke({"expression": "1 / 0"})
    assert result.startswith(PREFIX_TOOL_ERROR)
    assert "division by zero" in result
