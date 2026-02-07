"""Scout Agent — Discovers new trading strategy repos on GitHub.

Searches the GitHub API for repositories created or updated in the last 24 hours
that match trading/quant keywords. Filters by language, stars, and README presence.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SEARCH_KEYWORDS = [
    "trading strategy",
    "algorithmic trading",
    "quant strategy",
    "trading bot",
    "backtest",
    "mean reversion",
    "momentum strategy",
    "crypto trading",
    "market making",
    "statistical arbitrage",
]

GITHUB_API = "https://api.github.com"
MIN_STARS = 2
PREFERRED_LANGUAGE = "Python"
# Pause between API requests to stay under rate limits
REQUEST_DELAY_SECONDS = 2


def _github_headers() -> dict:
    """Build request headers, including auth token if available."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _search_repos(keyword: str, since: str, headers: dict) -> list[dict]:
    """Search GitHub for repos matching a keyword pushed after *since* (ISO date)."""
    query = f'"{keyword}" pushed:>{since} stars:>={MIN_STARS}'
    params = {
        "q": query,
        "sort": "updated",
        "order": "desc",
        "per_page": 30,
    }

    try:
        resp = requests.get(
            f"{GITHUB_API}/search/repositories",
            headers=headers,
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("items", [])
    except requests.RequestException as exc:
        logger.warning("Search failed for keyword '%s': %s", keyword, exc)
        return []


def _has_readme(repo_full_name: str, headers: dict) -> bool:
    """Check whether a repo has a README file."""
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo_full_name}/readme",
            headers=headers,
            timeout=15,
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False


def _normalize(repo: dict) -> dict:
    """Extract the fields we care about from a raw GitHub API repo object."""
    return {
        "repo_url": repo.get("html_url", ""),
        "repo_name": repo.get("full_name", ""),
        "description": repo.get("description") or "",
        "stars": repo.get("stargazers_count", 0),
        "language": repo.get("language") or "",
        "created_at": repo.get("created_at", ""),
        "topics": repo.get("topics", []),
    }


def run(output_path: str | None = None) -> list[dict]:
    """Execute the scout scan and return discovered repos.

    Args:
        output_path: Optional override for the JSON output file.
                     Defaults to data/daily_scans/{date}.json relative to project root.

    Returns:
        List of repo dicts that passed all filters.
    """
    logger.info("Scout agent starting")
    headers = _github_headers()
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d")

    seen_urls: set[str] = set()
    results: list[dict] = []

    for keyword in SEARCH_KEYWORDS:
        logger.info("Searching keyword: %s", keyword)
        repos = _search_repos(keyword, since, headers)
        time.sleep(REQUEST_DELAY_SECONDS)

        for repo in repos:
            url = repo.get("html_url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Prefer Python repos but don't hard-exclude others
            lang = repo.get("language") or ""
            if lang and lang != PREFERRED_LANGUAGE:
                continue

            if not _has_readme(repo["full_name"], headers):
                logger.debug("Skipping %s — no README", repo["full_name"])
                time.sleep(REQUEST_DELAY_SECONDS)
                continue
            time.sleep(REQUEST_DELAY_SECONDS)

            entry = _normalize(repo)
            results.append(entry)
            logger.info("Found: %s (%d stars)", entry["repo_name"], entry["stars"])

    # Persist results
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if output_path is None:
        scan_dir = PROJECT_ROOT / "data" / "daily_scans"
        scan_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(scan_dir / f"{today}.json")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    logger.info("Scout complete — %d repos saved to %s", len(results), output_path)
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    repos = run()
    print(f"Discovered {len(repos)} repos")
