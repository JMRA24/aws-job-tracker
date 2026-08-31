"""Local MVP for tracking matching remote job postings from Remotive."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests


API_URL = "https://remotive.com/api/remote-jobs"
DEFAULT_CATEGORY = "software-dev"
DEFAULT_KEYWORDS = (
    "IT Operations",
    "automation",
    "DevOps",
    "cloud",
    "platform engineer",
    "SRE",
    "Python",
)
DEFAULT_SEEN_JOBS_FILE = "seen_jobs.json"
REQUEST_TIMEOUT_SECONDS = 15


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


def filter_jobs(jobs: list[Job]) -> list[Job]:
    """Return jobs whose title or description contains at least one keyword."""
    keywords = tuple(keyword.casefold() for keyword in get_keywords())
    matches: list[Job] = []

    for job in jobs:
        searchable_text = f"{job.get('title', '')} {job.get('description', '')}".casefold()
        if any(keyword in searchable_text for keyword in keywords):
            matches.append(job)

    return matches


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
