"""Analyst Agent — Reads repos and extracts strategy logic in plain English.

For each discovered repo, reads the README and up to 3 core Python files to produce
a structured strategy summary. Never extracts or stores actual code — only the
logical concept and trading idea.
"""

import json
import logging
import os
import re
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

GITHUB_API = "https://api.github.com"
REQUEST_DELAY_SECONDS = 2

# Files whose names suggest strategy logic
PRIORITY_NAME_PATTERNS = re.compile(r"(strategy|signal|trade|backtest|engine|core)", re.IGNORECASE)

STRATEGY_CATEGORIES = [
    "momentum",
    "mean-reversion",
    "arbitrage",
    "ML",
    "statistical",
    "breakout",
    "other",
]

EXCLUDE_KEYWORDS = [s.strip().lower() for s in os.environ.get("EXCLUDE_KEYWORDS", "arbitrage").split(",") if s.strip()]


def _github_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch_readme(repo_name: str, headers: dict) -> str:
    """Return decoded README text, or empty string on failure."""
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo_name}/readme",
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            return ""
        data = resp.json()
        import base64

        content = data.get("content", "")
        if data.get("encoding") == "base64" and content:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        return ""
    except Exception as exc:
        logger.warning("Failed to fetch README for %s: %s", repo_name, exc)
        return ""


def _list_python_files(repo_name: str, headers: dict) -> list[dict]:
    """List Python files in the repo root and one level deep via the tree API."""
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo_name}/git/trees/HEAD?recursive=1",
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        tree = resp.json().get("tree", [])
        return [
            item
            for item in tree
            if item.get("path", "").endswith(".py") and item.get("type") == "blob"
        ]
    except Exception as exc:
        logger.warning("Failed to list files for %s: %s", repo_name, exc)
        return []


def _pick_core_files(py_files: list[dict], limit: int = 3) -> list[dict]:
    """Select the most relevant Python files by name pattern then by size."""
    priority = [f for f in py_files if PRIORITY_NAME_PATTERNS.search(f.get("path", ""))]
    others = [f for f in py_files if f not in priority]
    # Sort each group by size descending
    priority.sort(key=lambda f: f.get("size", 0), reverse=True)
    others.sort(key=lambda f: f.get("size", 0), reverse=True)
    return (priority + others)[:limit]


def _fetch_file_content(repo_name: str, file_path: str, headers: dict) -> str:
    """Fetch a single file from the repo, return decoded text."""
    import base64

    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo_name}/contents/{file_path}",
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            return ""
        data = resp.json()
        content = data.get("content", "")
        if data.get("encoding") == "base64" and content:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        return ""
    except Exception as exc:
        logger.warning("Failed to fetch %s/%s: %s", repo_name, file_path, exc)
        return ""


def _strip_code_and_markdown(text: str) -> str:
    """Remove code blocks, inline code, markdown images/badges, and HTML from text.

    Returns plain prose suitable for concept extraction without code leakage.
    """
    # Remove fenced code blocks (``` ... ```)
    text = re.sub(r"```[^`]*```", "", text, flags=re.DOTALL)
    # Remove indented code blocks (4+ leading spaces or tab)
    text = re.sub(r"(?m)^[ \t]{4,}.*$", "", text)
    # Remove inline code (`...`)
    text = re.sub(r"`[^`]+`", "", text)
    # Remove markdown images and badges ![alt](url)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    # Remove markdown links but keep the label [label](url) → label
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Remove markdown headings markers (keep the text)
    text = re.sub(r"(?m)^#{1,6}\s+", "", text)
    # Remove horizontal rules
    text = re.sub(r"(?m)^[-*_]{3,}\s*$", "", text)
    # Remove blockquote markers (keep the text)
    text = re.sub(r"(?m)^>\s*", "", text)
    # Remove markdown emphasis markers
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"_{1,2}([^_]+)_{1,2}", r"\1", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _looks_like_code(text: str) -> bool:
    """Heuristic check: does a string look like a code snippet rather than prose?"""
    code_signals = [
        r"[=!<>]{2}",              # ==, !=, <=, >=
        r"\b(?:def |class |import |return |elif |else:)",  # Python keywords in code context
        r"\w+\.\w+\(",             # method calls like obj.method(
        r"\w+\[['\"\w]",           # dict/array access like data['key'] or data[0]
        r"^\s*#\s*\w",             # Python comments
        r"[;{}]",                  # braces / semicolons
        r"(?:print|raise|assert)\s*\(", # common statements
        r"(?:True|False|None)\b",  # Python literals
        r"^\s*(?:if|for|while)\s+\w+.*:\s*$",  # control flow lines ending in colon
        r"\)\s*$",                 # line ending with closing paren
        r"\b\w+\s*=\s*\S",        # assignment: x = value (rare in English prose)
        r"\w+\([^)]*\)",           # function call: func(args)
    ]
    matches = sum(1 for p in code_signals if re.search(p, text, re.MULTILINE))
    # If 2+ code signals fire, likely code
    return matches >= 2


def _extract_indicators(text: str) -> list[str]:
    """Find mentions of common technical indicators in text."""
    indicators = [
        "RSI", "MACD", "SMA", "EMA", "Bollinger Bands", "ATR",
        "VWAP", "OBV", "Stochastic", "ADX", "CCI", "Ichimoku",
        "Fibonacci", "Moving Average", "Volume Profile", "Supertrend",
        "Keltner", "Donchian", "Williams %R", "MFI", "ROC",
    ]
    found = []
    upper = text.upper()
    for ind in indicators:
        if ind.upper() in upper:
            found.append(ind)
    return found


def _classify_category(text: str) -> str:
    """Assign a strategy category based on keyword frequency."""
    lower = text.lower()
    scores: dict[str, int] = {}
    keyword_map = {
        "momentum": ["momentum", "trend", "breakout", "moving average crossover"],
        "mean-reversion": ["mean reversion", "revert", "oversold", "overbought", "bollinger"],
        "arbitrage": ["arbitrage", "arb", "spread", "pair trading", "triangular"],
        "ML": ["machine learning", "neural", "lstm", "random forest", "predict", "classifier", "deep learning"],
        "statistical": ["statistical", "z-score", "cointegration", "correlation", "regression"],
        "breakout": ["breakout", "resistance", "support", "range", "channel"],
    }
    for category, keywords in keyword_map.items():
        scores[category] = sum(lower.count(kw) for kw in keywords)

    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "other"


def _summarize_strategy(readme: str, file_contents: list[str]) -> dict:
    """Produce a plain-English strategy summary from README and file contents.

    IMPORTANT: This extracts logical concepts only — no code is stored.
    The raw code is used ONLY for keyword detection (indicators, category,
    timeframe, asset class). All human-readable output fields are derived
    exclusively from the cleaned README prose.
    """
    # Clean the README: strip code blocks, badges, markdown noise.
    # This cleaned version is used for all human-readable output fields.
    clean_readme = _strip_code_and_markdown(readme)

    # For keyword scanning (indicators, category, timeframe, asset class) we
    # use raw text from both README and code files. These are internal signals
    # used only for tagging — their raw text never appears in any output field.
    raw_combined = readme + "\n" + "\n".join(file_contents)
    indicators = _extract_indicators(raw_combined)
    category = _classify_category(raw_combined)

    # Extract timeframe hints
    timeframe = "not specified"
    tf_patterns = [
        (r"\b(\d+)\s*(?:min(?:ute)?|m)\b", "minute"),
        (r"\b(\d+)\s*(?:hour|h)\b", "hour"),
        (r"\b(?:daily|1d|1D)\b", "daily"),
        (r"\b(?:weekly|1w|1W)\b", "weekly"),
        (r"\b(?:tick)\b", "tick"),
    ]
    for pattern, label in tf_patterns:
        match = re.search(pattern, raw_combined, re.IGNORECASE)
        if match:
            if label in ("minute", "hour"):
                timeframe = f"{match.group(1)} {label}"
            else:
                timeframe = label
            break

    # Asset class hints
    asset_class = "not specified"
    asset_keywords = {
        "crypto": ["crypto", "bitcoin", "btc", "eth", "binance", "defi", "token", "perp", "perpetual"],
        "equities": ["stock", "equity", "equities", "s&p", "nasdaq", "nyse", "shares"],
        "forex": ["forex", "fx", "currency pair", "eur/usd", "gbp"],
        "futures": ["futures", "contract", "expiry", "cme"],
        "options": ["options", "call", "put", "strike", "expiration", "greeks"],
    }
    lower_raw = raw_combined.lower()
    for asset, keywords in asset_keywords.items():
        if any(kw in lower_raw for kw in keywords):
            asset_class = asset
            break

    # Exclusion (e.g., arbitrage) based on keyword match
    excluded = any(kw in lower_raw for kw in EXCLUDE_KEYWORDS)
    exclude_reason = f"contains excluded keyword(s): {', '.join(EXCLUDE_KEYWORDS)}" if excluded else ""

    # Hyperliquid compatibility heuristic
    hyperliquid_compatible = asset_class == "crypto" and "equities" not in lower_raw and "forex" not in lower_raw
    exchange_compatibility = ["hyperliquid"] if hyperliquid_compatible else []

    # --- Core concept: extracted from cleaned README prose only ---
    readme_excerpt = clean_readme[:2000].strip()
    paragraphs = [p.strip() for p in readme_excerpt.split("\n\n") if len(p.strip()) > 30]
    # Skip paragraphs that still look like code despite cleaning
    paragraphs = [p for p in paragraphs if not _looks_like_code(p)]
    core_concept = paragraphs[0] if paragraphs else "Strategy concept not clearly described in README."
    # Truncate to 2 sentences max
    sentences = re.split(r'(?<=[.!?])\s+', core_concept)
    core_concept = " ".join(sentences[:2])
    if len(core_concept) > 300:
        core_concept = core_concept[:297] + "..."

    # --- Entry/exit logic: extracted from cleaned README only (never raw code) ---
    return {
        "core_concept": core_concept,
        "entry_logic": _extract_logic_hint(clean_readme, "entry"),
        "exit_logic": _extract_logic_hint(clean_readme, "exit"),
        "indicators": indicators,
        "timeframe": timeframe,
        "asset_class": asset_class,
        "category": category,
        "excluded": excluded,
        "exclude_reason": exclude_reason,
        "hyperliquid_compatible": hyperliquid_compatible,
        "exchange_compatibility": exchange_compatibility,
    }


def _extract_logic_hint(text: str, direction: str) -> str:
    """Try to find a sentence describing entry or exit logic from prose text.

    Only accepts matches that read like natural language, rejecting anything
    that looks like a code snippet.
    """
    patterns = {
        "entry": [r"(?:entry|buy|long|open)\s*(?:signal|when|if|condition|rule)[^.]*\.",
                  r"(?:go long|enter|buy)\s+when[^.]*\."],
        "exit": [r"(?:exit|sell|close|stop)[^.]*(?:signal|when|if|condition|rule)[^.]*\.",
                 r"(?:take profit|stop loss|exit)\s+when[^.]*\."],
    }
    for pattern in patterns.get(direction, []):
        for match in re.finditer(pattern, text, re.IGNORECASE):
            hint = match.group(0).strip()
            if _looks_like_code(hint):
                continue
            if len(hint) > 200:
                hint = hint[:197] + "..."
            return hint
    return f"No explicit {direction} logic described."


def run(repos: list[dict] | None = None, input_path: str | None = None) -> list[dict]:
    """Analyze repos and append strategy summaries.

    Args:
        repos: List of repo dicts from scout agent. If None, reads from input_path.
        input_path: Path to scout output JSON.

    Returns:
        List of repo dicts with a 'strategy_summary' field added.
    """
    if repos is None:
        if input_path is None:
            raise ValueError("Provide either repos list or input_path")
        with open(input_path, encoding="utf-8") as f:
            repos = json.load(f)

    logger.info("Analyst agent starting — %d repos to analyze", len(repos))
    headers = _github_headers()
    analyzed: list[dict] = []

    for repo in repos:
        repo_name = repo["repo_name"]
        logger.info("Analyzing %s", repo_name)

        try:
            readme = _fetch_readme(repo_name, headers)
            time.sleep(REQUEST_DELAY_SECONDS)

            py_files = _list_python_files(repo_name, headers)
            time.sleep(REQUEST_DELAY_SECONDS)

            core_files = _pick_core_files(py_files)
            file_contents: list[str] = []
            for cf in core_files:
                content = _fetch_file_content(repo_name, cf["path"], headers)
                # We read the file to understand logic, but store NOTHING from it
                file_contents.append(content)
                time.sleep(REQUEST_DELAY_SECONDS)

            summary = _summarize_strategy(readme, file_contents)
            repo["strategy_summary"] = summary
            analyzed.append(repo)
            logger.info("  Category: %s | Indicators: %s", summary["category"], summary["indicators"])

        except Exception as exc:
            logger.error("Failed to analyze %s: %s", repo_name, exc)
            continue

    logger.info("Analyst complete — %d repos analyzed", len(analyzed))
    return analyzed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")

    import sys

    if len(sys.argv) > 1:
        result = run(input_path=sys.argv[1])
    else:
        # Try today's scan
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        default_path = PROJECT_ROOT / "data" / "daily_scans" / f"{today}.json"
        if default_path.exists():
            result = run(input_path=str(default_path))
        else:
            print(f"No scan file found at {default_path}. Run scout_agent first.")
            sys.exit(1)
    print(f"Analyzed {len(result)} repos")
    print(json.dumps(result, indent=2))
