"""Local MVP for tracking matching remote job postings from Remotive."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import requests


API_URL = "https://remotive.com/api/remote-jobs"
DEFAULT_CATEGORY = "software-dev"
DEFAULT_SEEN_JOBS_FILE = "seen_jobs.json"
REQUEST_TIMEOUT_SECONDS = 15

STRONG_KEYWORDS = (
    "IT Operations",
    "DevOps",
    "SRE",
    "platform engineer",
    "site reliability",
)
WEAK_KEYWORDS = (
    "automation",
    "cloud",
    "Python",
    "infrastructure",
)

STRONG_TITLE_WEIGHT = 6
STRONG_DESCRIPTION_WEIGHT = 3
WEAK_TITLE_WEIGHT = 2
WEAK_DESCRIPTION_WEIGHT = 1
DEFAULT_MIN_SCORE = 6  # at least one strong signal required

Job = dict[str, Any]


def get_keywords() -> tuple[str, ...]:
    """Return keywords from JOB_KEYWORDS or the default keyword list."""
    raw_keywords = os.getenv("JOB_KEYWORDS")
    if not raw_keywords:
        return DEFAULT_KEYWORDS

    keywords = tuple(keyword.strip() for keyword in raw_keywords.split(",") if keyword.strip())
    return keywords or DEFAULT_KEYWORDS


def get_category() -> str:
    """Return the Remotive category from REMOTIVE_CATEGORY or the default."""
    return os.getenv("REMOTIVE_CATEGORY", DEFAULT_CATEGORY)


def get_seen_jobs_path() -> Path:
    """Return the path used for local seen-job ID storage."""
    return Path(os.getenv("SEEN_JOBS_FILE", DEFAULT_SEEN_JOBS_FILE))


def fetch_jobs() -> list[Job]:
    """Fetch remote jobs from Remotive and return the jobs list."""
    try:
        response = requests.get(
            API_URL,
            params={"category": get_category()},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.Timeout:
        print(f"Request timed out after {REQUEST_TIMEOUT_SECONDS} seconds.")
        return []
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        print(f"Remotive API returned HTTP {status_code}.")
        return []
    except requests.RequestException as exc:
        print(f"Could not fetch jobs from Remotive: {exc}")
        return []

    try:
        payload = response.json()
    except ValueError:
        print("Remotive API returned a response that was not valid JSON.")
        return []

    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        print("Remotive API response did not include a jobs list.")
        return []

    return [job for job in jobs if isinstance(job, dict)]


def _compile_keyword_patterns(keywords: tuple[str, ...]) -> list[re.Pattern[str]]:
    """Compile case-insensitive, whole-word patterns for each keyword."""
    return [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in keywords]


def score_job(
    job: Job,
    strong_patterns: list[re.Pattern[str]],
    weak_patterns: list[re.Pattern[str]],
) -> int:
    """Score a job by keyword hits in its TITLE only.

    Titles are reliable; descriptions (especially from staffing agencies)
    often repeat a generic stack blurb across unrelated roles, so they are
    intentionally ignored for the match decision.
    """
    title = job.get("title", "") or ""
    score = 0
    for pattern in strong_patterns:
        if pattern.search(title):
            score += STRONG_TITLE_WEIGHT
    for pattern in weak_patterns:
        if pattern.search(title):
            score += WEAK_TITLE_WEIGHT
    return score


def filter_jobs(jobs: list[Job]) -> list[Job]:
    """Return matching jobs, most relevant first, above the minimum score."""
    min_score = int(os.getenv("MIN_SCORE", DEFAULT_MIN_SCORE))
    strong_patterns = _compile_keyword_patterns(STRONG_KEYWORDS)
    weak_patterns = _compile_keyword_patterns(WEAK_KEYWORDS)

    scored = ((score_job(job, strong_patterns, weak_patterns), job) for job in jobs)
    matches = sorted(
        (pair for pair in scored if pair[0] >= min_score),
        key=lambda pair: pair[0],
        reverse=True,
    )
    return [job for _, job in matches]

def load_seen_ids() -> set[str]:
    """Load previously seen job IDs from local JSON storage."""
    seen_jobs_path = get_seen_jobs_path()
    if not seen_jobs_path.exists():
        return set()

    try:
        with seen_jobs_path.open("r", encoding="utf-8") as file:
            seen_ids = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read {seen_jobs_path}: {exc}. Starting with no seen jobs.")
        return set()

    if not isinstance(seen_ids, list):
        print(f"{seen_jobs_path} did not contain a JSON list. Starting with no seen jobs.")
        return set()

    return {str(seen_id) for seen_id in seen_ids}


def save_seen_ids(ids: set[str]) -> None:
    """Save seen job IDs to local JSON storage."""
    seen_jobs_path = get_seen_jobs_path()

    try:
        with seen_jobs_path.open("w", encoding="utf-8") as file:
            json.dump(sorted(ids), file, indent=2)
            file.write("\n")
    except OSError as exc:
        print(f"Could not save seen job IDs to {seen_jobs_path}: {exc}")


def format_job(job: Job) -> str:
    """Format a job for console output."""
    title = job.get("title", "Untitled job")
    company = job.get("company_name", "Unknown company")
    location = job.get("candidate_required_location", "Unspecified location")
    job_type = job.get("job_type") or "Unspecified type"
    publication_date = job.get("publication_date", "Unknown publication date")
    url = job.get("url", "No URL provided")

    return (
        f"{title}\n"
        f"Company: {company}\n"
        f"Location: {location}\n"
        f"Type: {job_type}\n"
        f"Published: {publication_date}\n"
        f"Source: Remotive\n"
        f"URL: {url}"
    )


def run() -> None:
    """Fetch, filter, deduplicate, print, and persist matching jobs."""
    jobs = fetch_jobs()
    if not jobs:
        print("No jobs fetched.")
        return

    matching_jobs = filter_jobs(jobs)
    seen_ids = load_seen_ids()
    new_matches = [job for job in matching_jobs if str(job.get("id")) not in seen_ids]

    if not new_matches:
        print("No new matching jobs found.")
    else:
        print(f"Found {len(new_matches)} new matching job(s):\n")
        print("\n---\n".join(format_job(job) for job in new_matches))

    seen_ids.update(str(job.get("id")) for job in matching_jobs if job.get("id") is not None)
    save_seen_ids(seen_ids)


if __name__ == "__main__":
    run()
