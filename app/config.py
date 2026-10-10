"""Application configuration.

Values are read from environment variables so the same code can run in local
development, tests, and (hypothetically) production without changes.
"""
import os
from pathlib import Path

# Root directory of the project (one level up from this file's package).
BASE_DIR = Path(__file__).resolve().parent.parent

# Database. SQLite by default so the project runs with zero external setup.
# Point DATABASE_URL at Postgres/MySQL to use a different relational DB.
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'certificates.db'}")

# Directory where generated certificate PDFs are written.
OUTPUT_DIR = Path(os.getenv("CERT_OUTPUT_DIR", BASE_DIR / "generated_certificates"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Number of worker threads used to process jobs concurrently.
MAX_WORKERS = int(os.getenv("CERT_MAX_WORKERS", "4"))

# Safety cap on how many recipients a single job may contain.
MAX_RECIPIENTS_PER_JOB = int(os.getenv("CERT_MAX_RECIPIENTS", "10000"))

# When true, jobs are processed inline (synchronously) during the create
# request instead of on a background thread. Useful for deterministic tests.
PROCESS_SYNC = os.getenv("CERT_PROCESS_SYNC", "false").lower() in {"1", "true", "yes"}
