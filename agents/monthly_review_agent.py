"""Monthly Review Agent — summarizes all strategies and forward-test results.

Reads data/forward_tests.json and data/daily_scans/*.json to produce
monthly_reports/{YYYY-MM}_review.md.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run() -> str:
    month_str = datetime.now(timezone.utc).strftime("%Y-%m")
    out_dir = PROJECT_ROOT / "monthly_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{month_str}_review.md"

    forward_path = PROJECT_ROOT / "data" / "forward_tests.json"
    forward = json.loads(forward_path.read_text()) if forward_path.exists() else []

    # Aggregate discovered strategies this month
    scans_dir = PROJECT_ROOT / "data" / "daily_scans"
    discovered = []
    if scans_dir.exists():
        for f in scans_dir.glob(f"{month_str}-*.json"):
            try:
                discovered.extend(json.loads(f.read_text()))
            except Exception:
                continue

    lines = [
        "# Monthly Strategy Review",
        f"**Month:** {month_str}",
        "",
        f"Strategies discovered: {len(discovered)}",
        f"Strategies in forward test: {len(forward)}",
        "",
        "## Forward-Test Summary",
    ]

    if not forward:
        lines.append("No forward-test data available.")
    else:
        for s in forward:
            lines.append(f"### {s.get('name','Unnamed Strategy')}")
            lines.append(f"- Status: {s.get('status','In Forward Test')}")
            lines.append(f"- Win rate: {s.get('win_rate','n/a')}")
            lines.append(f"- Sharpe: {s.get('sharpe','n/a')}")
            lines.append(f"- Max drawdown: {s.get('max_drawdown','n/a')}")
            lines.append(f"- PnL: {s.get('pnl','n/a')}")
            lines.append(f"- Recommendation: {s.get('recommendation','continue testing')}")
            lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return str(out_path)


if __name__ == "__main__":
    print(run())
