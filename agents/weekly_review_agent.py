"""Weekly Review Agent — summarizes forward-test performance.

Reads data/forward_tests.json and produces weekly_review/{date}_review.md.
If no forward-test data exists, produces a placeholder report.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run() -> str:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = PROJECT_ROOT / "weekly_review"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}_review.md"

    data_path = PROJECT_ROOT / "data" / "forward_tests.json"
    if data_path.exists():
        data = json.loads(data_path.read_text())
    else:
        data = []

    lines = [
        "# Weekly Strategy Review",
        f"**Date:** {date_str}",
        "",
    ]

    if not data:
        lines.append("No forward-test data found. Run forward tests to populate this report.")
        out_path.write_text("\n".join(lines), encoding="utf-8")
        return str(out_path)

    lines.append(f"Strategies under test: {len(data)}")
    lines.append("")

    for s in data:
        lines.append(f"## {s.get('name','Unnamed Strategy')}")
        lines.append(f"- Status: {s.get('status','In Forward Test')}")
        lines.append(f"- Win rate: {s.get('win_rate','n/a')}")
        lines.append(f"- Sharpe: {s.get('sharpe','n/a')}")
        lines.append(f"- Max drawdown: {s.get('max_drawdown','n/a')}")
        lines.append(f"- PnL: {s.get('pnl','n/a')}")
        lines.append(f"- Notes: {s.get('notes','')}")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return str(out_path)


if __name__ == "__main__":
    print(run())
