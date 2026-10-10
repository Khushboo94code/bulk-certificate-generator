"""Tests for the background processing path and the generator directly.

These bypass the sync-mode endpoint to exercise the real thread-pool worker.
"""
import time

from app.crud import create_job, get_job
from app.database import SessionLocal
from app.generator import render_certificate
from app.models import JobStatus
from app.schemas import JobCreate
from app.worker import submit_job


def test_background_job_completes(tmp_path):
    payload = JobCreate(
        course_name="Async Course",
        issuer="Issuer",
        recipients=[{"name": f"User {i}"} for i in range(5)],
    )
    db = SessionLocal()
    job = create_job(db, payload)
    job_id = job.id
    db.close()

    submit_job(job_id)

    # Poll for completion (background thread uses the same SQLite file).
    deadline = time.time() + 15
    status = None
    while time.time() < deadline:
        check = SessionLocal()
        status = get_job(check, job_id).status
        check.close()
        if status in (JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS):
            break
        time.sleep(0.1)

    assert status == JobStatus.COMPLETED

    verify = SessionLocal()
    job = get_job(verify, job_id)
    assert job.succeeded == 5
    assert job.failed == 0
    verify.close()


def test_render_certificate_writes_pdf(tmp_path):
    path = render_certificate(
        cert_id="abc-123",
        recipient_name="Jane Doe",
        course_name="Test Course",
        issuer="Test Issuer",
        issue_date="2026-10-10",
        output_dir=tmp_path,
    )
    assert path.exists()
    assert path.read_bytes().startswith(b"%PDF")
