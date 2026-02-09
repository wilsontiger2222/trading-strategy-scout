"""Reporter Agent — Generates a daily digest and sends it via Telegram.

Selects the top 5 strategies by feasibility score, generates a markdown report,
saves it to disk, and sends a summary to Telegram.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TOP_N = 5
FRAMEWORK_KEYWORDS = [
    "framework", "library", "sdk", "engine", "platform", "toolkit",
    "backtesting", "backtest", "data pipeline", "infrastructure"
]


def _format_report(top_repos: list[dict], all_repos: list[dict], date_str: str) -> str:
    """Generate the full markdown report."""
    lines = [
        f"# Trading Strategy Scout — Daily Digest",
        f"**Date:** {date_str}",
        f"**Repos scanned:** {len(all_repos)}",
        f"**Novel strategies found:** {sum(1 for r in all_repos if r.get('dedup_status') != 'duplicate')}",
        "",
        "---",
        "",
    ]

    if not top_repos:
        lines.append("*No new strategies found today.*")
        return "\n".join(lines)

    for i, repo in enumerate(top_repos, 1):
        summary = repo.get("strategy_summary", {})
        feasibility = repo.get("feasibility", {})
        scores = feasibility.get("scores", {})

        lines.append(f"## #{i}: {repo['repo_name']}")
        lines.append("")
        lines.append(f"**Stars:** {repo.get('stars', 0)} | "
                      f"**Language:** {repo.get('language', 'N/A')} | "
                      f"**Category:** {summary.get('category', 'N/A')}")
        lines.append(f"**Link:** {repo.get('repo_url', '')}")
        lines.append("")
        lines.append(f"### Concept")
        lines.append(summary.get("core_concept", "N/A"))
        lines.append("")
        lines.append(f"### Implementation Blueprint")
        lines.append(f"- Entry: {summary.get('entry_logic', 'N/A')}")
        lines.append(f"- Exit: {summary.get('exit_logic', 'N/A')}")
        lines.append(f"- Timeframe: {summary.get('timeframe', 'N/A')}")
        lines.append(f"- Asset class: {summary.get('asset_class', 'N/A')}")
        lines.append(f"- Data requirements: {summary.get('data_requirements', 'ohlcv')}")
        lines.append(f"- Tier: {summary.get('tier', 'Unclear')} — {summary.get('tier_reason', '')}")
        lines.append("")
        lines.append(f"### JSON Strategy Schema")
        lines.append("```json")
        lines.append(json.dumps({
            "name": repo.get('repo_name', ''),
            "category": summary.get('category', 'other'),
            "entry": summary.get('entry_logic', ''),
            "exit": summary.get('exit_logic', ''),
            "timeframe": summary.get('timeframe', ''),
            "asset_class": summary.get('asset_class', ''),
            "data_requirements": summary.get('data_requirements', 'ohlcv')
        }, indent=2))
        lines.append("```")
        lines.append("")
        lines.append(f"### Indicators")
        indicators = summary.get("indicators", [])
        lines.append(", ".join(indicators) if indicators else "None detected")
        lines.append("")
        lines.append(f"### Feasibility Scores")
        lines.append(f"- Implementation complexity: {scores.get('implementation_complexity', '-')}/10")
        lines.append(f"- Capital efficiency: {scores.get('capital_efficiency', '-')}/10")
        lines.append(f"- Edge durability: {scores.get('edge_durability', '-')}/10")
        lines.append(f"- Platform compatibility: {scores.get('platform_compatibility', '-')}/10")
        lines.append(f"- Data requirements: {scores.get('data_requirements', '-')}/10")
        lines.append(f"- **Overall: {feasibility.get('overall_score', 0):.2f}/10**")
        lines.append(f"- **Recommendation: {feasibility.get('recommendation', '-').upper()}**")
        if feasibility.get('notes'):
            lines.append(f"- **Notes:** {feasibility.get('notes')}")
        lines.append("")
        lines.append(f"**Hyperliquid compatible:** {'YES' if summary.get('hyperliquid_compatible') else 'NO/PARTIAL'} — {summary.get('hyperliquid_reason', 'n/a')}")
        lines.append(f"**Quality score:** {repo.get('quality_score', 0)} / 10")
        lines.append(f"**Status:** {repo.get('status', 'New')}")
        lines.append("")
        lines.append(f"**Novelty:** {repo.get('dedup_status', 'N/A')} (similarity: {repo.get('max_similarity', 0):.2f})")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _format_telegram_message(top_repos: list[dict], date_str: str) -> str:
    """Format a shorter Telegram-friendly summary."""
    lines = [
        f"📊 *Trading Strategy Scout — {date_str}*",
        "",
    ]

    if not top_repos:
        lines.append("No new strategies found today.")
        return "\n".join(lines)

    for i, repo in enumerate(top_repos, 1):
        summary = repo.get("strategy_summary", {})
        feasibility = repo.get("feasibility", {})
        score = feasibility.get("overall_score", 0)
        rec = feasibility.get("recommendation", "?")

        rec_emoji = {"pursue": "🟢", "monitor": "🟡", "skip": "🔴"}.get(rec, "⚪")

        lines.append(f"*{i}. {repo['repo_name']}* ⭐{repo.get('stars', 0)}")
        lines.append(f"   {summary.get('category', '?')} | {summary.get('tier','Unclear')} | Score: {score:.1f}/10 {rec_emoji} {rec.upper()} | Hyperliquid: {'YES' if summary.get('hyperliquid_compatible') else 'NO/PARTIAL'}")
        lines.append(f"   Data: {summary.get('data_requirements','ohlcv')} | Quality: {repo.get('quality_score',0)}/10 | Status: {repo.get('status','New')}")
        lines.append(f"   {summary.get('core_concept', 'N/A')[:120]}")
        lines.append(f"   [View repo]({repo.get('repo_url', '')})")
        lines.append("")

    return "\n".join(lines)


async def _send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    """Send a message via Telegram HTTP API (no SDK)."""
    import requests
    try:
        # Split message if too long (Telegram limit is 4096 chars)
        if len(message) > 4000:
            message = message[:3997] + "..."

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if resp.ok:
            logger.info("Telegram message sent successfully")
            return True
        logger.error("Failed to send Telegram message: %s", resp.text)
        return False
    except Exception as exc:
        logger.error("Failed to send Telegram message: %s", exc)
        return False


def run(repos: list[dict] | None = None, input_path: str | None = None) -> str:
    """Generate report and send Telegram notification.

    Args:
        repos: List of scored repo dicts.
        input_path: Path to JSON file with scored repos.

    Returns:
        Path to the saved report file.
    """
    if repos is None:
        if input_path is None:
            raise ValueError("Provide either repos list or input_path")
        with open(input_path, encoding="utf-8") as f:
            repos = json.load(f)

    logger.info("Reporter agent starting — %d repos to report", len(repos))

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Select top N non-duplicate strategies (tiered + exclude frameworks)
    eligible = [
        r for r in repos
        if r.get("dedup_status") != "duplicate"
    ]
    tier_rank = {"Tier 1": 3, "Tier 2": 2, "Tier 3": 1, "Unclear": 0}

    def _is_framework(r):
        hay = " ".join([
            (r.get("repo_name") or ""),
            (r.get("description") or ""),
            (r.get("strategy_summary", {}).get("core_concept") or "")
        ]).lower()
        return any(k in hay for k in FRAMEWORK_KEYWORDS)

    def _score(r):
        summary = r.get("strategy_summary", {})
        tier = summary.get("tier", "Unclear")
        feas = r.get("feasibility", {}).get("overall_score", 0)
        quality = r.get("quality_score", 0)
        hay = " ".join([
            (r.get("repo_name") or ""),
            (r.get("description") or ""),
            (summary.get("core_concept") or "")
        ]).lower()
        hyperliquid_boost = 0.2 if "hyperliquid" in hay else 0
        return (tier_rank.get(tier, 0), feas + hyperliquid_boost, quality)

    eligible = [r for r in eligible if not _is_framework(r) and r.get("strategy_summary", {}).get("tier") != "Unclear"]
    eligible.sort(key=_score, reverse=True)
    top = eligible[:TOP_N]

    # Generate markdown report
    report_md = _format_report(top, repos, date_str)

    # Save report
    report_dir = PROJECT_ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{date_str}_digest.md"
    report_path.write_text(report_md, encoding="utf-8")
    logger.info("Report saved to %s", report_path)

    # Send Telegram notification
    bot_token = os.environ.get("BOT_TOKEN", "")
    chat_id = os.environ.get("CHAT_ID", "")

    if bot_token and chat_id:
        tg_message = _format_telegram_message(top, date_str)
        asyncio.run(_send_telegram(tg_message, bot_token, chat_id))
    else:
        logger.warning("Telegram credentials not configured — skipping notification")

    logger.info("Reporter complete")
    return str(report_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")

    import sys

    if len(sys.argv) > 1:
        report = run(input_path=sys.argv[1])
    else:
        print("Usage: python -m agents.reporter_agent <input.json>")
        sys.exit(1)
    print(f"Report saved to: {report}")
