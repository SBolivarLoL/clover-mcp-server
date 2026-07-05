"""Contract test: MCP tool-schema token budget.

Guards against the tool definitions silently growing past the committed
baseline (scripts/schema_budget.baseline.json). If this test fails, either the
growth is unintentional (fix the schema) or intentional (re-run
`uv run python scripts/schema_budget.py --update-baseline` and commit it).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from schema_budget import BASELINE_PATH, GROWTH_TOLERANCE, measure  # noqa: E402


async def test_schema_budget_within_baseline() -> None:
    total, method = await measure()
    assert total > 0

    baseline = json.loads(BASELINE_PATH.read_text())
    assert baseline["method"] == method, (
        "baseline was measured with a different token-counting method; "
        "re-run --update-baseline to refresh it"
    )

    limit = baseline["total_tokens"] * (1 + GROWTH_TOLERANCE)
    assert total <= limit, f"schema token count {total} exceeds baseline budget {limit:.0f}"
