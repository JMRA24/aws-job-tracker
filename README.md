# Job Tracker

A command-line tool that aggregates remote and hybrid tech job postings from
multiple public job boards, ranks them by how well their title matches a set of
target roles, filters them by geography, and reports only postings it hasn't
shown before.

Built as **Phase 0** of a project with a clear path to a serverless AWS
deployment (see [Roadmap](#roadmap)). This phase runs entirely locally and has
no cloud dependencies.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)

## Why

Job boards each have their own site, their own search, and their own noise.
Checking several of them by hand every day is slow, and the same generic
"senior engineer" postings show up again and again. This tool pulls from
several boards at once, keeps only the roles that actually match a target
profile (DevOps / SRE / Platform Engineering, remote or hybrid, in Latin
America or the Netherlands), and remembers what it has already reported so each
run surfaces only what's new.

## Features

- **Four job sources** queried in a single run: Remotive, RemoteOK, Arbeitnow,
  and Get on Board (Latin America).
- **A normalized internal schema** so every source flows through the same
  pipeline regardless of its response format.
- **Title-based relevance scoring** that weights strong role keywords (DevOps,
  SRE, Platform Engineer) above weak ones (Python, cloud) and ignores
  descriptions, which cuts false positives dramatically.
- **A heuristic location filter** that keeps only remote/hybrid roles in target
  geographies, and can be toggled off.
- **Deduplication across runs** via a local store, so repeated runs only print
  new postings.
- **Per-source failure isolation**: if one API is down or changes its format,
  that source returns nothing and the others keep working.

## How it works

Each source has its own fetch function that translates that API's response into
one shared internal shape. The rest of the pipeline never needs to know how
many sources exist or what their fields are called:

```
 sources ──► normalize ──► merge ──► score by title ──► filter by location ──► dedup ──► report
(4 APIs)     (per source)            (relevance)         (remote + geo)        (new only)
```

Adding a fifth source is writing one `fetch_*` function and adding it to the
`SOURCES` registry. Nothing else changes.

## Sources

| Source       | Focus                     | Auth | Notes                                            |
|--------------|---------------------------|------|--------------------------------------------------|
| Remotive     | International remote       | None | Filtered to the software-development category    |
| RemoteOK     | International remote       | None | Requires a User-Agent header                     |
| Arbeitnow    | Europe / remote            | None | Unix timestamps normalized to ISO dates          |
| Get on Board | Latin America              | None | Search endpoint (JSON:API, beta); queried per keyword |

## Getting started

### Prerequisites

- Python 3.10 or newer
- `pip`

### Install

```bash
git clone https://github.com/JMRA24/aws-job-tracker.git
cd aws-job-tracker
pip install -r requirements.txt
```

### Run

```bash
python job_tracker.py
```

The first run prints all current matches and records them. Later runs print
only postings that are new since the last run.

## Configuration

All configuration is read from environment variables, with sensible defaults —
nothing needs to be set to run the tool.

| Variable            | Default           | What it does                                                        |
|---------------------|-------------------|---------------------------------------------------------------------|
| `MIN_SCORE`         | `6`               | Minimum title relevance score for a posting to be kept.             |
| `LOCATION_FILTER`   | `1`               | Set to `0` to disable the location filter and see every match.      |
| `REMOTIVE_CATEGORY` | `software-dev`    | The Remotive category to query.                                     |
| `SEEN_JOBS_FILE`    | `seen_jobs.json`  | Path to the local file that stores already-seen job IDs.            |

Example — see every relevant title regardless of location:

```bash
LOCATION_FILTER=0 python job_tracker.py
```

The target roles (`STRONG_KEYWORDS` / `WEAK_KEYWORDS`) and geographies
(`LATAM_SIGNALS` / `NL_SIGNALS`) are defined as editable constants at the top of
`job_tracker.py`.

## Design decisions

A few choices worth calling out, because they came from real behaviour of the
data rather than theory:

- **Scoring on the title, not the description.** An early version matched
  keywords anywhere in the posting. Staffing agencies repeat a generic stack
  blurb ("you'll work with DevOps, cloud, automation…") across unrelated roles,
  so a React or QA posting scored the same as a real DevOps role. Scoring only
  the title, where the words are reliable, cut a sample run from six results
  (five irrelevant) to one exact match.
- **Honest empty fields over guessed ones.** Get on Board's search endpoint
  doesn't return the company name. Rather than parse it out of the URL slug —
  which would be wrong as often as right — the tool labels it `See listing` and
  keeps the link. A field that's honestly blank is better than one that's
  confidently wrong.
- **Location filtering is heuristic, and says so.** Every source encodes
  location differently (region lists, city names, status codes), so the filter
  matches on text signals and is intentionally easy to tune or switch off,
  rather than pretending to be exact.

## Roadmap

This local MVP is designed to migrate to a serverless AWS architecture without
rewriting its core logic — the storage and orchestration are already isolated
for exactly that.

- **Phase 1 — AWS (Cloud Practitioner).** Move the run into a Lambda triggered
  on a schedule by EventBridge; replace the local JSON store with DynamoDB;
  send new matches through SNS; keep secrets in SSM Parameter Store.
- **Phase 2 — Infrastructure as Code (Terraform Associate).** Define all of the
  above in Terraform with reusable modules and remote state in S3.
- **Phase 3 — Observability (SysOps / CloudOps).** Add CloudWatch alarms, a
  dead-letter queue for failed notifications, and a dashboard.

## Project structure

```
.
├── job_tracker.py      # the tool
├── requirements.txt    # dependencies
├── .gitignore
└── README.md
```

## License

Add a `LICENSE` file (MIT is a common choice for portfolio projects) if you
want to make reuse terms explicit.