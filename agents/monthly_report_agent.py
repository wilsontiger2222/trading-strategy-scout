"""Monthly Report Agent — aggregates weekly reviews and strategy outcomes.

Runs on last day of month. Aggregates weekly reviews and strategy states.
Outputs monthly_reports/{YYYY-MM}_review.md and sends Telegram notification.
"""

import json
import os
import asyncio
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

async def _send_telegram(message: str) -> bool:
    try:
        from telegram import Bot
        bot = Bot(token=os.environ.get("BOT_TOKEN", ""))
        chat_id = os.environ.get("CHAT_ID", "")
        if not bot or not chat_id:
            return False
        if len(message) > 4000:
            message = message[:3997] + "..."
        await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown", disable_web_page_preview=True)
        return True
    except Exception:
        return False


def run() -> str:
    month_str = datetime.now(timezone.utc).strftime("%Y-%m")
    out_dir = PROJECT_ROOT / "monthly_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{month_str}_review.md"

    # Aggregate weekly reviews
    weekly_dir = PROJECT_ROOT / "weekly_reviews"
    weekly_files = sorted(weekly_dir.glob(f"{month_str}-*_review.md")) if weekly_dir.exists() else []

    # Load active strategies
    active_path = PROJECT_ROOT / "data" / "active_strategies.json"
    active = json.loads(active_path.read_text()) if active_path.exists() else []

    lines = [
        "# Monthly Strategy Report",
        f"**Month:** {month_str}",
        "",
        f"Weekly reviews: {len(weekly_files)}",
        f"Active strategies: {len(active)}",
        "",
        "## Strategy Outcomes",
    ]

    if not active:
        lines.append("No active strategies found.")
    else:
        for s in active:
            lines.append(f"### {s.get('name','Unnamed Strategy')}")
            lines.append(f"- Status: {s.get('status','Forward Test')}")
            lines.append(f"- PnL: {s.get('performance',{}).get('pnl_pct','n/a')}%")
            lines.append(f"- Win rate: {s.get('performance',{}).get('win_rate','n/a')}")
            lines.append(f"- Sharpe: {s.get('performance',{}).get('sharpe','n/a')}")
            lines.append(f"- Max drawdown: {s.get('performance',{}).get('max_drawdown','n/a')}")
            lines.append(f"- Recommendation: {s.get('recommendation','continue / modify / discard')}")
            lines.append("")

    lines.append("## Weekly Review Index")
    for f in weekly_files:
        lines.append(f"- {f.name}")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    # Telegram notification
    if os.environ.get("BOT_TOKEN") and os.environ.get("CHAT_ID"):
        asyncio.run(_send_telegram(f"📅 Monthly strategy report ready: {out_path.name}"))

    return str(out_path)


if __name__ == "__main__":
    print(run())
