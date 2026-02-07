"""Feasibility Agent — Scores strategies on practical implementation criteria.

Evaluates each non-duplicate strategy on five dimensions and produces a weighted
overall score plus a recommendation (pursue / monitor / skip).
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Weights for the overall feasibility score
WEIGHTS = {
    "implementation_complexity": 0.20,
    "capital_efficiency": 0.25,
    "edge_durability": 0.25,
    "platform_compatibility": 0.15,
    "data_requirements": 0.15,
}

# Thresholds for recommendation
PURSUE_THRESHOLD = 7.0
MONITOR_THRESHOLD = 4.5


def _score_implementation_complexity(summary: dict) -> int:
    """Score 1-10: higher = easier to implement from scratch."""
    score = 5  # baseline
    indicators = summary.get("indicators", [])
    category = summary.get("category", "")
    entry = summary.get("entry_logic", "").lower()
    exit_logic = summary.get("exit_logic", "").lower()

    # Simple indicator-based strategies are easier
    if len(indicators) <= 2:
        score += 2
    elif len(indicators) <= 4:
        score += 1
    elif len(indicators) > 6:
        score -= 2

    # ML strategies are harder to implement from scratch
    if category == "ML":
        score -= 3
    elif category in ("momentum", "mean-reversion", "breakout"):
        score += 1

    # If entry/exit logic is clearly described, easier to implement
    if "no explicit" not in entry:
        score += 1
    if "no explicit" not in exit_logic:
        score += 1

    return max(1, min(10, score))


def _score_capital_efficiency(summary: dict) -> int:
    """Score 1-10: higher = works better with small capital (<$10k)."""
    score = 5
    asset = summary.get("asset_class", "").lower()
    category = summary.get("category", "")
    timeframe = summary.get("timeframe", "").lower()

    # Crypto is the most capital-efficient for small accounts
    if asset == "crypto":
        score += 3
    elif asset == "forex":
        score += 1
    elif asset in ("futures", "options"):
        score -= 1
    elif asset == "equities":
        score -= 1

    # Arbitrage often needs large capital for meaningful returns
    if category == "arbitrage":
        score -= 2
    # Market making needs capital reserves
    concept = summary.get("core_concept", "").lower()
    if "market making" in concept:
        score -= 2

    # Higher frequency = more trades = more fees eating into small accounts
    if "minute" in timeframe or "tick" in timeframe:
        score -= 1

    return max(1, min(10, score))


def _score_edge_durability(summary: dict) -> int:
    """Score 1-10: higher = alpha likely still valid, not crowded."""
    score = 5
    category = summary.get("category", "")
    concept = summary.get("core_concept", "").lower()
    indicators = summary.get("indicators", [])

    # Simple moving average crossovers are extremely crowded
    crowded_indicators = {"SMA", "EMA", "MACD", "RSI"}
    crowded_count = len(set(indicators) & crowded_indicators)
    if crowded_count >= 3:
        score -= 2
    elif crowded_count >= 2:
        score -= 1

    # Statistical/ML approaches may have more durable edges
    if category == "ML":
        score += 1
    elif category == "statistical":
        score += 1

    # If it's on GitHub, the alpha is somewhat reduced
    score -= 1

    # Novel-sounding concepts get a small boost
    novel_keywords = ["alternative data", "sentiment", "on-chain", "orderbook", "microstructure"]
    if any(kw in concept for kw in novel_keywords):
        score += 2

    return max(1, min(10, score))


def _score_platform_compatibility(summary: dict) -> int:
    """Score 1-10: higher = easier to run on crypto exchanges (Hyperliquid, Binance, etc.)."""
    score = 5
    asset = summary.get("asset_class", "").lower()
    timeframe = summary.get("timeframe", "").lower()
    concept = summary.get("core_concept", "").lower()

    if asset == "crypto":
        score += 3
    elif asset in ("equities", "forex"):
        score -= 1
    elif asset == "not specified":
        score += 1  # often adaptable

    # Perpetuals / leverage-friendly strategies
    if any(kw in concept for kw in ["perpetual", "perp", "leverage", "futures"]):
        score += 1

    # Very high frequency is hard on exchange APIs
    if "tick" in timeframe:
        score -= 2
    elif "minute" in timeframe:
        val = re.search(r"(\d+)", timeframe)
        if val and int(val.group(1)) < 5:
            score -= 1

    return max(1, min(10, score))


def _score_data_requirements(summary: dict) -> int:
    """Score 1-10: higher = uses freely available data."""
    score = 7  # most strategies use standard OHLCV data
    concept = summary.get("core_concept", "").lower()
    indicators = summary.get("indicators", [])

    # Standard indicators work with OHLCV
    expensive_keywords = [
        "alternative data", "satellite", "sentiment", "news feed",
        "order flow", "level 2", "options chain", "dark pool",
    ]
    for kw in expensive_keywords:
        if kw in concept:
            score -= 2

    # Volume profile needs tick data
    if "Volume Profile" in indicators:
        score -= 1

    # On-chain data is mostly free
    if "on-chain" in concept:
        score += 1

    return max(1, min(10, score))


def _compute_feasibility(summary: dict) -> dict:
    """Compute all scores and the weighted overall feasibility score."""
    scores = {
        "implementation_complexity": _score_implementation_complexity(summary),
        "capital_efficiency": _score_capital_efficiency(summary),
        "edge_durability": _score_edge_durability(summary),
        "platform_compatibility": _score_platform_compatibility(summary),
        "data_requirements": _score_data_requirements(summary),
    }

    overall = sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)
    overall = round(overall, 2)

    if overall >= PURSUE_THRESHOLD:
        recommendation = "pursue"
    elif overall >= MONITOR_THRESHOLD:
        recommendation = "monitor"
    else:
        recommendation = "skip"

    return {
        "scores": scores,
        "overall_score": overall,
        "recommendation": recommendation,
    }


def run(repos: list[dict] | None = None, input_path: str | None = None) -> list[dict]:
    """Score feasibility for each non-duplicate strategy.

    Args:
        repos: List of deduplicated repo dicts.
        input_path: Path to JSON file with deduplicated repos.

    Returns:
        List of repo dicts with 'feasibility' field added.
    """
    if repos is None:
        if input_path is None:
            raise ValueError("Provide either repos list or input_path")
        with open(input_path, encoding="utf-8") as f:
            repos = json.load(f)

    logger.info("Feasibility agent starting — %d repos to score", len(repos))
    results: list[dict] = []

    for repo in repos:
        dedup_status = repo.get("dedup_status", "novel")
        summary = repo.get("strategy_summary", {})

        if dedup_status == "duplicate":
            logger.info("  Skipping duplicate: %s", repo["repo_name"])
            repo["feasibility"] = {
                "scores": {},
                "overall_score": 0,
                "recommendation": "skip (duplicate)",
            }
            results.append(repo)
            continue

        feasibility = _compute_feasibility(summary)
        repo["feasibility"] = feasibility
        logger.info(
            "  %s — score: %.2f — %s",
            repo["repo_name"],
            feasibility["overall_score"],
            feasibility["recommendation"],
        )
        results.append(repo)

    logger.info("Feasibility scoring complete")
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import sys

    if len(sys.argv) > 1:
        result = run(input_path=sys.argv[1])
    else:
        print("Usage: python -m agents.feasibility_agent <input.json>")
        sys.exit(1)

    for r in sorted(result, key=lambda x: x.get("feasibility", {}).get("overall_score", 0), reverse=True):
        f = r.get("feasibility", {})
        print(f"{r['repo_name']:40s} | score={f.get('overall_score', 0):.2f} | {f.get('recommendation', '')}")
