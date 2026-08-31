# AWS Job Tracker

Phase 0 local MVP for tracking remote tech job vacancies from the Remotive public API.

The script fetches jobs from the `software-dev` category, filters them by configurable keywords, deduplicates previously seen matching jobs using `seen_jobs.json`, and prints only new matches to the console.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python job_tracker.py
```

## Configuration

Defaults are defined in `job_tracker.py` and can be overridden with environment variables:

- `REMOTIVE_CATEGORY`: Remotive category slug. Default: `software-dev`
- `JOB_KEYWORDS`: comma-separated keyword list. Default includes `IT Operations`, `automation`, `DevOps`, `cloud`, `platform engineer`, `SRE`, and `Python`
- `SEEN_JOBS_FILE`: local JSON file for deduplication. Default: `seen_jobs.json`

Example:

```bash
$env:JOB_KEYWORDS = "DevOps,Python,SRE"
python job_tracker.py
```

## Notes

No AWS, Terraform, DynamoDB, or Lambda code is included in this phase. The storage functions are isolated so the local JSON file can later be replaced with DynamoDB without changing the filtering and orchestration logic.
