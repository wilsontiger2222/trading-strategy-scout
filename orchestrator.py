"""Orchestrator — Chains all sub-agents into a daily pipeline.

Pipeline: Scout → Analyst → Dedup → Feasibility → Reporter

Handles errors gracefully — if one repo fails analysis, it skips and continues.
Logs all activity to logs/{date}.log. Auto-creates missing directories on first run.
Designed to be run via cron daily or called by an external automation system.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Project root is wherever this file lives
PROJECT_ROOT = Path(__file__).resolve().parent

# Load env vars before importing agents (they may read tokens at import time)
load_dotenv(PROJECT_ROOT / ".env")

from agents import scout_agent, analyst_agent, dedup_agent, feasibility_agent, reporter_agent


def _slug(s: str) -> str:
    return ''.join(c.lower() if c.isalnum() else '-' for c in s).strip('-')


def _auto_register_strategies(repos) -> int:
    """Auto-register new strategies into data/active_strategies.json.

    Criteria: recommendation == 'pursue' and not duplicate. Uses repo name as id.
    """
    active_path = PROJECT_ROOT / "data" / "active_strategies.json"
    active_path.parent.mkdir(parents=True, exist_ok=True)
    if active_path.exists():
        try:
            active = json.loads(active_path.read_text())
        except Exception:
            active = []
    else:
        active = []

    existing_ids = {a.get("id") for a in active}
    added = 0

    for r in repos:
        if r.get("dedup_status") == "duplicate":
            continue
        if r.get("feasibility", {}).get("recommendation") != "pursue":
            continue
        name = r.get("strategy_name") or r.get("repo_name") or r.get("name") or "Unnamed Strategy"
        sid = _slug(name)
        if sid in existing_ids:
            continue
        entry = {
            "id": sid,
            "name": name,
            "status": "forward-test",
            "strategy_tag": r.get("summary", {}).get("strategy_tag") or r.get("summary", {}).get("category") or "strategy",
            "summary": r.get("summary", {}).get("overview") or r.get("summary", {}).get("one_liner") or "",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        active.append(entry)
        existing_ids.add(sid)
        added += 1

    active_path.write_text(json.dumps(active, indent=2), encoding="utf-8")
    return added


def _setup_logging(date_str: str) -> logging.Logger:
    """Configure logging to both file and stdout."""
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date_str}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Clear any existing handlers to avoid duplicates on re-runs
    root_logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    return logging.getLogger("orchestrator")


def _ensure_directories() -> None:
    """Create all runtime directories if they don't exist."""
    for subdir in ["data", "data/daily_scans", "reports", "logs"]:
        (PROJECT_ROOT / subdir).mkdir(parents=True, exist_ok=True)


def run() -> None:
    """Execute the full daily pipeline."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _ensure_directories()
    logger = _setup_logging(date_str)

    logger.info("=" * 60)
    logger.info("Trading Strategy Scout — Daily Run: %s", date_str)
    logger.info("=" * 60)

    # --- Stage 1: Scout ---
    logger.info("Stage 1/5: Scout Agent")
    try:
        repos = scout_agent.run()
        logger.info("Scout found %d repos", len(repos))
    except Exception as exc:
        logger.error("Scout agent failed: %s", exc, exc_info=True)
        logger.info("Pipeline aborted — no repos to analyze")
        return

    if not repos:
        logger.info("No repos found today. Pipeline complete.")
        # Still generate an empty report
        try:
            reporter_agent.run(repos=[])
        except Exception as exc:
            logger.error("Reporter failed on empty run: %s", exc)
        return

    # --- Stage 2: Analyst ---
    logger.info("Stage 2/5: Analyst Agent")
    try:
        analyzed = analyst_agent.run(repos=repos)
        logger.info("Analyst processed %d / %d repos", len(analyzed), len(repos))
    except Exception as exc:
        logger.error("Analyst agent failed: %s", exc, exc_info=True)
        logger.info("Continuing with raw repo data")
        analyzed = repos

    # --- Stage 3: Dedup ---
    logger.info("Stage 3/5: Dedup Agent")
    try:
        deduped = dedup_agent.run(repos=analyzed)
        novel_count = sum(1 for r in deduped if r.get("dedup_status") != "duplicate")
        logger.info("Dedup: %d total, %d non-duplicate", len(deduped), novel_count)
    except Exception as exc:
        logger.error("Dedup agent failed: %s", exc, exc_info=True)
        logger.info("Continuing without dedup — marking all as novel")
        for r in analyzed:
            r["dedup_status"] = "novel"
            r["max_similarity"] = 0.0
        deduped = analyzed

    # --- Stage 4: Feasibility ---
    logger.info("Stage 4/5: Feasibility Agent")
    try:
        scored = feasibility_agent.run(repos=deduped)
        pursue_count = sum(
            1 for r in scored
            if r.get("feasibility", {}).get("recommendation") == "pursue"
        )
        logger.info("Feasibility: %d pursue, scored %d total", pursue_count, len(scored))
    except Exception as exc:
        logger.error("Feasibility agent failed: %s", exc, exc_info=True)
        scored = deduped

    # --- Stage 5: Reporter ---
    logger.info("Stage 5/5: Reporter Agent")
    try:
        report_path = reporter_agent.run(repos=scored)
        logger.info("Report saved to %s", report_path)
    except Exception as exc:
        logger.error("Reporter agent failed: %s", exc, exc_info=True)

    # Auto-register new strategies for forward testing
    try:
        added = _auto_register_strategies(scored)
        if added:
            logger.info("Auto-registered %d new strategies into active_strategies.json", added)
    except Exception as exc:
        logger.error("Auto-register failed: %s", exc)

    # Save the full pipeline output for debugging
    output_path = PROJECT_ROOT / "data" / "daily_scans" / f"{date_str}_full.json"
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(scored, f, indent=2)
        logger.info("Full pipeline output saved to %s", output_path)
    except Exception as exc:
        logger.error("Failed to save full output: %s", exc)

    logger.info("=" * 60)
    logger.info("Pipeline complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    run()
