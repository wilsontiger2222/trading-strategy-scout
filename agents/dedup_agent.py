"""Dedup Agent — Detects duplicate strategies using TF-IDF cosine similarity.

Maintains a persistent strategy database and compares each incoming strategy
summary against existing entries. Flags duplicates (>0.8 similarity) and
novel strategies (<0.5 similarity).
"""

import json
import logging
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DB_PATH = PROJECT_ROOT / "data" / "strategy_db.json"

DUPLICATE_THRESHOLD = 0.8
NOVEL_THRESHOLD = 0.5


def _load_db() -> list[dict]:
    """Load the persistent strategy database."""
    if DB_PATH.exists():
        with open(DB_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_db(db: list[dict]) -> None:
    """Persist the strategy database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)


def _build_description_text(repo: dict) -> str:
    """Combine all textual fields of a strategy into a single string for TF-IDF."""
    summary = repo.get("strategy_summary", {})
    parts = [
        repo.get("description", ""),
        summary.get("core_concept", ""),
        summary.get("entry_logic", ""),
        summary.get("exit_logic", ""),
        summary.get("category", ""),
        summary.get("asset_class", ""),
        summary.get("timeframe", ""),
        " ".join(summary.get("indicators", [])),
        " ".join(repo.get("topics", [])),
    ]
    return " ".join(parts)


def _compute_max_similarity(new_text: str, existing_texts: list[str]) -> float:
    """Compute the maximum cosine similarity between new_text and existing_texts."""
    if not existing_texts:
        return 0.0

    corpus = existing_texts + [new_text]
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(corpus)

    # Compare the last vector (new entry) against all previous ones
    new_vec = tfidf_matrix[-1]
    existing_vecs = tfidf_matrix[:-1]
    similarities = cosine_similarity(new_vec, existing_vecs).flatten()

    return float(similarities.max()) if len(similarities) > 0 else 0.0


def run(repos: list[dict] | None = None, input_path: str | None = None) -> list[dict]:
    """Deduplicate strategy list against the persistent database.

    Each repo dict gets a 'dedup_status' field: "duplicate", "similar", or "novel",
    and a 'max_similarity' score.

    Args:
        repos: List of analyzed repo dicts.
        input_path: Path to JSON file with analyzed repos.

    Returns:
        List of repo dicts with dedup annotations.
    """
    if repos is None:
        if input_path is None:
            raise ValueError("Provide either repos list or input_path")
        with open(input_path, encoding="utf-8") as f:
            repos = json.load(f)

    logger.info("Dedup agent starting — %d repos to check", len(repos))

    db = _load_db()
    existing_texts = [_build_description_text(entry) for entry in db]

    results: list[dict] = []
    new_entries_added = 0

    for repo in repos:
        new_text = _build_description_text(repo)
        if not new_text.strip():
            repo["dedup_status"] = "novel"
            repo["max_similarity"] = 0.0
            results.append(repo)
            continue

        sim = _compute_max_similarity(new_text, existing_texts)
        repo["max_similarity"] = round(sim, 4)

        if sim > DUPLICATE_THRESHOLD:
            repo["dedup_status"] = "duplicate"
            logger.info("  DUPLICATE (%.2f): %s", sim, repo["repo_name"])
        elif sim < NOVEL_THRESHOLD:
            repo["dedup_status"] = "novel"
            logger.info("  NOVEL (%.2f): %s", sim, repo["repo_name"])
            db.append(repo)
            existing_texts.append(new_text)
            new_entries_added += 1
        else:
            repo["dedup_status"] = "similar"
            logger.info("  SIMILAR (%.2f): %s", sim, repo["repo_name"])
            # Still add to DB — it's not a clear duplicate
            db.append(repo)
            existing_texts.append(new_text)
            new_entries_added += 1

        results.append(repo)

    _save_db(db)
    logger.info(
        "Dedup complete — %d duplicate, %d similar, %d novel, %d added to DB",
        sum(1 for r in results if r["dedup_status"] == "duplicate"),
        sum(1 for r in results if r["dedup_status"] == "similar"),
        sum(1 for r in results if r["dedup_status"] == "novel"),
        new_entries_added,
    )
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import sys

    if len(sys.argv) > 1:
        result = run(input_path=sys.argv[1])
    else:
        print("Usage: python -m agents.dedup_agent <input.json>")
        sys.exit(1)

    non_dup = [r for r in result if r["dedup_status"] != "duplicate"]
    print(f"Total: {len(result)} | Non-duplicate: {len(non_dup)}")
    print(json.dumps(result, indent=2))
