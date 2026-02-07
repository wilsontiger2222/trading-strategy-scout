"""Weekly Review Agent — compares forward-test performance vs benchmark.

Loads data/active_strategies.json, pulls their performance fields, compares
against a simple BTC buy-and-hold benchmark, outputs weekly_reviews/{date}_review.md,
and sends a Telegram summary.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
import os
import asyncio

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _btc_benchmark(start_price: float, end_price: float) -> float:
    if start_price and end_price:
        return (end_price - start_price) / start_price * 100
    return 0.0


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
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = PROJECT_ROOT / "weekly_reviews"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}_review.md"

    data_path = PROJECT_ROOT / "data" / "active_strategies.json"
    data = json.loads(data_path.read_text()) if data_path.exists() else []

    lines = [
        "# Weekly Strategy Review",
        f"**Date:** {date_str}",
        "",
    ]

    if not data:
        lines.append("No active strategies found in data/active_strategies.json")
        out_path.write_text("\n".join(lines), encoding="utf-8")
        return str(out_path)

    lines.append(f"Strategies under test: {len(data)}")
    lines.append("")

    summary_lines = [f"📈 *Weekly Review — {date_str}*", ""]

    for s in data:
        name = s.get("name", "Unnamed Strategy")
        perf = s.get("performance", {})
        bench = s.get("benchmark", {})
        strat_pnl = perf.get("pnl_pct", 0)
        btc_pnl = _btc_benchmark(bench.get("btc_start"), bench.get("btc_end"))
        delta = strat_pnl - btc_pnl

        lines.append(f"## {name}")
        lines.append(f"- Status: {s.get('status','Forward Test')}")
        lines.append(f"- PnL: {strat_pnl:.2f}%")
        lines.append(f"- Win rate: {perf.get('win_rate','n/a')}")
        lines.append(f"- Sharpe: {perf.get('sharpe','n/a')}")
        lines.append(f"- Max drawdown: {perf.get('max_drawdown','n/a')}")
        lines.append(f"- Benchmark (BTC buy&hold): {btc_pnl:.2f}%")
        lines.append(f"- Outperformance: {delta:.2f}%")
        lines.append(f"- Suggestions: {s.get('suggestions','n/a')}")
        lines.append("")

        summary_lines.append(f"*{name}* — PnL {strat_pnl:.2f}%, BTC {btc_pnl:.2f}%, Δ {delta:.2f}%")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    # Telegram summary
    if os.environ.get("BOT_TOKEN") and os.environ.get("CHAT_ID"):
        asyncio.run(_send_telegram("\n".join(summary_lines)))

    return str(out_path)


if __name__ == "__main__":
    print(run())
