"""Local MVP for tracking matching remote job postings from Remotive."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import requests


# --- Source endpoints -------------------------------------------------------
REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
REMOTEOK_URL = "https://remoteok.com/api"
ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
GETONBRD_URL = "https://www.getonbrd.com/api/v0/search/jobs"

DEFAULT_CATEGORY = "software-dev"  # Remotive category
DEFAULT_SEEN_JOBS_FILE = "seen_jobs.json"
REQUEST_TIMEOUT_SECONDS = 15

# Some public APIs (RemoteOK) block requests without a User-Agent header.
BROWSER_HEADERS = {"User-Agent": "aws-job-tracker/1.0 (+https://github.com)"}

# --- Scoring configuration --------------------------------------------------
# Strong keywords are role signals: if they appear in the TITLE, the job is
# almost certainly relevant. Weak keywords appear in almost any tech posting.
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
WEAK_TITLE_WEIGHT = 2
DEFAULT_MIN_SCORE = 6  # at least one strong keyword in the title

# --- Location configuration -------------------------------------------------
# A job is kept if it looks remote/hybrid AND matches one of these geographies,
# or is remote with no geographic restriction. Edit these lists freely.
# NOTE: location data is inconsistent across sources, so this is heuristic.
# Turn it off with LOCATION_FILTER=0 to see every scored match.
LATAM_SIGNALS = (
    "latam", "latin america", "américa latina", "americas", "colombia",
    "chile", "argentina", "mexico", "méxico", "brazil", "brasil", "peru",
    "perú", "uruguay", "ecuador", "bolivia", "paraguay", "costa rica",
)
NL_SIGNALS = (
    "netherlands", "nederland", "amsterdam", "rotterdam", "the hague",
    "holland", "dutch",
    # 'europe'/'emea' are generous: NL is in the EU, but this also lets in
    # other European remote roles. Remove them to tighten to NL only.
    "europe", "emea",
)
UNRESTRICTED_SIGNALS = ("worldwide", "anywhere", "global")

# Sources that only ever list remote jobs (no on-site postings).
REMOTE_ONLY_SOURCES = {"remotive", "remoteok"}


Job = dict[str, Any]


# --- Config helpers ---------------------------------------------------------
def get_category() -> str:
    """Return the Remotive category from REMOTIVE_CATEGORY or the default."""
    return os.getenv("REMOTIVE_CATEGORY", DEFAULT_CATEGORY)


def get_seen_jobs_path() -> Path:
    """Return the path used for local seen-job ID storage."""
    return Path(os.getenv("SEEN_JOBS_FILE", DEFAULT_SEEN_JOBS_FILE))


def location_filter_enabled() -> bool:
    """Location filtering is on by default; set LOCATION_FILTER=0 to disable."""
    return os.getenv("LOCATION_FILTER", "1").lower() not in ("0", "false", "no")


# --- HTTP + normalization ---------------------------------------------------
def _http_get_json(
    url: str,
    params: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
) -> Any:
    """GET a URL and return parsed JSON, or None on any network/parse error."""
    try:
        response = requests.get(
            url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except requests.Timeout:
        print(f"  {url}: request timed out")
        return None
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        print(f"  {url}: HTTP {status}")
        return None
    except requests.RequestException as exc:
        print(f"  {url}: request failed ({exc})")
        return None

    try:
        return response.json()
    except ValueError:
        print(f"  {url}: response was not valid JSON")
        return None


def _format_timestamp(value: Any) -> Optional[str]:
    """Convert a Unix timestamp (int or numeric string) to an ISO date.

    Leaves already-formatted date strings untouched.
    """
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return str(value) if value else None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _normalize(
    source: str,
    job_id: Any,
    title: Any,
    company: Any,
    location: Any,
    job_type: Any,
    published: Any,
    url: Any,
    description: Any,
) -> Job:
    """Build a normalized job dict shared by every source.

    The id is prefixed with the source name so IDs never collide across
    sources (e.g. 'remoteok:123' vs 'remotive:123').
    """
    return {
        "id": f"{source}:{job_id}",
        "title": (title or "").strip(),
        "description": description or "",
        "company": (company or "Unknown company"),
        "location": (location or "Unspecified location"),
        "job_type": (job_type or "Unspecified type"),
        "published": (published or "Unknown date"),
        "url": (url or ""),
        "source": source,
    }


# --- Source fetchers (one per API) ------------------------------------------
def fetch_remotive() -> list[Job]:
    """Fetch and normalize jobs from Remotive (international remote)."""
    payload = _http_get_json(REMOTIVE_URL, params={"category": get_category()})
    raw = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    return [
        _normalize(
            "remotive",
            j.get("id"),
            j.get("title"),
            j.get("company_name"),
            j.get("candidate_required_location"),
            j.get("job_type"),
            j.get("publication_date"),
            j.get("url"),
            j.get("description"),
        )
        for j in raw
        if isinstance(j, dict)
    ]


def fetch_remoteok() -> list[Job]:
    """Fetch and normalize jobs from RemoteOK (international remote).

    RemoteOK returns a JSON array whose first element is a legal/metadata
    object (no 'position' field), so we skip anything without a title.
    """
    payload = _http_get_json(REMOTEOK_URL, headers=BROWSER_HEADERS)
    if not isinstance(payload, list):
        return []
    jobs: list[Job] = []
    for j in payload:
        if not isinstance(j, dict) or not j.get("position"):
            continue
        jobs.append(
            _normalize(
                "remoteok",
                j.get("id") or j.get("slug"),
                j.get("position"),
                j.get("company"),
                j.get("location"),
                None,  # RemoteOK has no reliable job-type field
                _format_timestamp(j.get("epoch")) or j.get("date"),
                j.get("url"),
                j.get("description"),
            )
        )
    return jobs


def fetch_arbeitnow() -> list[Job]:
    """Fetch and normalize jobs from Arbeitnow (EU / remote)."""
    payload = _http_get_json(ARBEITNOW_URL)
    raw = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    jobs: list[Job] = []
    for j in raw:
        if not isinstance(j, dict):
            continue
        job_types = j.get("job_types")
        job_type = (
            ", ".join(job_types)
            if isinstance(job_types, list) and job_types
            else None
        )
        jobs.append(
            _normalize(
                "arbeitnow",
                j.get("slug"),
                j.get("title"),
                j.get("company_name"),
                j.get("location"),
                job_type,
                _format_timestamp(j.get("created_at")),
                j.get("url"),
                j.get("description"),
            )
        )
    return jobs


def fetch_getonbrd() -> list[Job]:
    """Fetch and normalize jobs from Get on Board (Latin America).

    Get on Board's endpoint is a SEARCH endpoint: it requires a query term
    and won't return everything at once. So we search once per strong keyword
    and merge the results, de-duplicating by job id. Its API is JSON:API-shaped
    (fields live under 'attributes') and in beta, so this stays defensive:
    on any failure it returns [] and the other sources keep working.

    The search endpoint does not expose the company name, so we label it
    'See listing' rather than guessing it from the URL slug.
    """
    seen: set[str] = set()
    jobs: list[Job] = []

    for query in STRONG_KEYWORDS:
        payload = _http_get_json(
            GETONBRD_URL,
            params={"query": query, "per_page": 50},
            headers=BROWSER_HEADERS,
        )
        raw = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            continue

        for item in raw:
            if not isinstance(item, dict):
                continue
            job_id = item.get("id")
            if job_id in seen:
                continue
            seen.add(job_id)

            attrs = item.get("attributes") or {}
            location = attrs.get("remote_modality") or (
                "Remote" if attrs.get("remote") else None
            )
            url = (item.get("links") or {}).get("public_url")

            jobs.append(
                _normalize(
                    "getonbrd",
                    job_id,
                    attrs.get("title"),
                    attrs.get("company_name") or "See listing",
                    location,
                    None,  # Get on Board exposes seniority, not a job type
                    _format_timestamp(attrs.get("published_at")),
                    url,
                    attrs.get("description"),
                )
            )

    return jobs


# Registry: add a source here and it flows through the whole pipeline.
SOURCES: tuple[Callable[[], list[Job]], ...] = (
    fetch_remotive,
    fetch_remoteok,
    fetch_arbeitnow,
    fetch_getonbrd,
)


def fetch_jobs() -> list[Job]:
    """Fetch from every registered source and merge into one list."""
    all_jobs: list[Job] = []
    print("Fetching from sources:")
    for source in SOURCES:
        name = source.__name__.replace("fetch_", "")
        jobs = source()
        print(f"  {name}: {len(jobs)} job(s)")
        all_jobs.extend(jobs)
    return all_jobs


# --- Scoring / filtering ----------------------------------------------------
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


# --- Location filtering -----------------------------------------------------
def _is_remote_or_hybrid(job: Job) -> bool:
    """Best-effort check that a job is remote or hybrid (not on-site)."""
    source = job["source"]
    location = job["location"].lower()
    if source in REMOTE_ONLY_SOURCES:
        return True
    if source == "getonbrd":
        # Keeps remote_local / fully_remote / hybrid; drops no_remote.
        return "no_remote" not in location
    return "remote" in location or "hybrid" in location


def _geography_matches(job: Job) -> bool:
    """Check the job is in a target geography (LATAM, NL) or unrestricted."""
    if job["source"] == "getonbrd":
        return True  # Get on Board is a LATAM-focused platform
    text = f"{job['location']} {job['title']}".lower()
    signals = LATAM_SIGNALS + NL_SIGNALS + UNRESTRICTED_SIGNALS
    return any(signal in text for signal in signals)


def filter_by_location(jobs: list[Job]) -> list[Job]:
    """Keep only remote/hybrid jobs in a target geography (LATAM or NL)."""
    if not location_filter_enabled():
        return jobs
    return [
        job
        for job in jobs
        if _is_remote_or_hybrid(job) and _geography_matches(job)
    ]


# --- Storage (swap this for DynamoDB in Phase 1) ----------------------------
def load_seen_ids() -> set[str]:
    """Load previously seen job IDs from local JSON storage."""
    seen_jobs_path = get_seen_jobs_path()
    if not seen_jobs_path.exists():
        return set()
    try:
        with seen_jobs_path.open("r", encoding="utf-8") as file:
            seen_ids = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read {seen_jobs_path}: {exc}. Starting fresh.")
        return set()
    if not isinstance(seen_ids, list):
        print(f"{seen_jobs_path} did not contain a JSON list. Starting fresh.")
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


# --- Output -----------------------------------------------------------------
def format_job(job: Job) -> str:
    """Format a normalized job for console output."""
    return (
        f"{job['title']}\n"
        f"Company: {job['company']}\n"
        f"Location: {job['location']}\n"
        f"Type: {job['job_type']}\n"
        f"Published: {job['published']}\n"
        f"Source: {job['source']}\n"
        f"URL: {job['url']}"
    )


def run() -> None:
    """Fetch, filter, deduplicate, print, and persist matching jobs."""
    jobs = fetch_jobs()
    if not jobs:
        print("No jobs fetched from any source.")
        return

    matching_jobs = filter_jobs(jobs)
    matching_jobs = filter_by_location(matching_jobs)

    seen_ids = load_seen_ids()
    new_matches = [job for job in matching_jobs if job["id"] not in seen_ids]

    if not new_matches:
        print("\nNo new matching jobs found.")
    else:
        print(f"\nFound {len(new_matches)} new matching job(s):\n")
        print("\n---\n".join(format_job(job) for job in new_matches))

    seen_ids.update(job["id"] for job in matching_jobs)
    save_seen_ids(seen_ids)


if __name__ == "__main__":
    run()
