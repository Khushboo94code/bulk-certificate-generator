# Bulk Certificate Generator

A backend API that accepts a single request containing many recipients and
generates a PDF certificate for each one from a predefined template. Jobs run
in the background; clients poll for progress and download finished
certificates.

Built with **FastAPI**, **SQLAlchemy** (SQLite by default), and **ReportLab**.

---

## Features

- **Web UI** at `/` — submit recipients, watch live progress, download PDFs.
- One request → many certificates (true bulk generation).
- Background processing; the create endpoint returns a job id immediately.
- Per-recipient failure isolation — one bad recipient never blocks the rest.
- Job status with live success/failure/pending counts, plus per-certificate
  status and error reasons.
- Download generated certificates as PDF.

---

## Project layout

```
app/
  config.py      # env-driven configuration
  database.py    # SQLAlchemy engine/session + table creation
  models.py      # Job and Certificate ORM models
  schemas.py     # Pydantic request/response models + recipient validation
  generator.py   # ReportLab PDF certificate template
  worker.py      # background thread-pool job processing
  crud.py        # database access helpers
  main.py        # FastAPI app and routes
  static/
    index.html   # single-page web UI (served at /)
tests/
  conftest.py    # fixtures (temp DB, sync processing)
  test_api.py    # end-to-end API tests
  test_worker.py # background path + generator unit tests
```

---

## Setup

Requires Python 3.11+.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running the application

```bash
uvicorn app.main:app --reload
```

Then open **`http://127.0.0.1:8000/`** for the web UI. The interactive API docs
(Swagger UI) are at `http://127.0.0.1:8000/docs`. The SQLite database
(`certificates.db`) and output directory (`generated_certificates/`) are
created automatically on first run.

## Running the tests

```bash
pytest
```

---

## API

### 1. Submit a generation request

`POST /jobs` → `202 Accepted`

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "course_name": "Introduction to Machine Learning",
    "issuer": "Acme Academy",
    "issue_date": "2026-10-10",
    "recipients": [
      {"name": "Alice Smith", "email": "alice@example.com"},
      {"name": "Bob Jones",   "email": "bob@example.com"}
    ]
  }'
```

`course_name`, `issuer`, and a non-empty `recipients` list are required.
`issue_date` is optional and defaults to today. `email` is optional per
recipient.

Response:

```json
{
  "id": "920a5ff8-01ca-4357-8f4d-56865895b0d3",
  "course_name": "Introduction to Machine Learning",
  "issuer": "Acme Academy",
  "issue_date": "2026-10-10",
  "status": "pending",
  "total": 2, "succeeded": 0, "failed": 0, "pending": 2
}
```

### 2. Check job status / progress

`GET /jobs/{job_id}` — returns job counts plus every certificate's status and
any error message.

```bash
curl http://127.0.0.1:8000/jobs/<job_id>
```

Job status values: `pending`, `processing`, `completed`,
`completed_with_errors`, `failed`.

### 3. List certificates in a job

`GET /jobs/{job_id}/certificates` — optional `?status_filter=success|failed|pending`.

```bash
curl "http://127.0.0.1:8000/jobs/<job_id>/certificates?status_filter=failed"
```

### 4. Retrieve a generated certificate

`GET /certificates/{cert_id}` — certificate metadata.
`GET /certificates/{cert_id}/download` — the PDF file.

```bash
curl -OJ http://127.0.0.1:8000/certificates/<cert_id>/download
```

Downloading a certificate that failed or hasn't finished returns `409`.

---

## Design decisions

**Framework & storage.** FastAPI for concise request validation (Pydantic) and
auto-generated docs. SQLAlchemy over SQLite so the project runs with zero
external setup; `DATABASE_URL` can point at Postgres/MySQL without code changes.

**Data model.** A `jobs` row holds the shared certificate fields
(course, issuer, date) and aggregate counts; a `certificates` row per recipient
holds that recipient's status, error, and file path. Per-recipient rows are
what make failure isolation and progress tracking natural.

**Bulk processing — background thread pool.** `POST /jobs` persists the job and
its recipients, then hands the job id to an in-process
`ThreadPoolExecutor` and returns `202` immediately, so one request can enqueue
thousands of recipients without the client waiting. I chose a thread pool over
Celery/RQ because it needs no broker (Redis/RabbitMQ) and keeps the project to
a single run command — appropriate for this scope. PDF rendering writes to disk
and releases the GIL enough for threads to give real concurrency. The worker
commits after each certificate, so `GET /jobs/{id}` shows progress while the
job is still running.

*Production note:* for durability across restarts and horizontal scaling you'd
replace `worker.py` with a real task queue. Everything funnels through
`process_job(job_id)`, so the swap is localized.

**Validation & failure handling.** Structural validation (missing
`course_name`, empty recipient list, too many recipients) is enforced at the API
boundary and rejects the whole request with `422`. Semantic per-recipient
validation (blank name, malformed email) happens *during* generation: an
invalid or un-renderable recipient is recorded as a `failed` certificate with a
reason and the batch continues. This directly satisfies "one failure must not
block other valid certificates."

**Certificate generation.** ReportLab draws a single predefined A4-landscape
template (title, recipient name, course, issuer, date, and a certificate id
that doubles as a verification reference). Chosen over an HTML-to-PDF engine to
avoid a headless-browser dependency.

**Testing.** Tests run with `CERT_PROCESS_SYNC=true` so job processing happens
inline for deterministic assertions, while `tests/test_worker.py` separately
exercises the real background thread-pool path by polling to completion.

### Configuration (environment variables)

| Variable              | Default                      | Purpose                                  |
|-----------------------|------------------------------|------------------------------------------|
| `DATABASE_URL`        | `sqlite:///./certificates.db`| Database connection string               |
| `CERT_OUTPUT_DIR`     | `./generated_certificates`   | Where PDF files are written              |
| `CERT_MAX_WORKERS`    | `4`                          | Background worker threads                |
| `CERT_MAX_RECIPIENTS` | `10000`                      | Max recipients allowed per job           |
| `CERT_PROCESS_SYNC`   | `false`                      | Process jobs inline instead of in background |
