"""Background job processing.

Design choice: jobs are processed on an in-process ``ThreadPoolExecutor``.

Why this (and not Celery/RQ)?
  * The POST request returns immediately with a job id, so a single request
    can enqueue thousands of recipients without the client waiting — that is
    the core "bulk" requirement.
  * It needs zero external infrastructure (no Redis/RabbitMQ), so the project
    runs with a single command, which matters for a review/take-home.
  * PDF rendering releases the GIL enough and is I/O-ish (disk writes), so a
    thread pool gives real concurrency across recipients.

Production note: for horizontal scaling and durability across restarts you
would swap this module for a real task queue (Celery/RQ/arq). The rest of the
code is unaffected because everything goes through ``process_job(job_id)``.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from app.config import MAX_WORKERS
from app.database import SessionLocal
from app.generator import render_certificate
from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas import validate_recipient

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


def submit_job(job_id: str) -> None:
    """Hand a job off to the background thread pool."""
    _executor.submit(process_job, job_id)


def process_job(job_id: str) -> None:
    """Generate every certificate in a job, isolating per-recipient failures.

    Opens its own DB session because it may run on a worker thread distinct
    from the request thread.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            logger.error("process_job: job %s not found", job_id)
            return

        job.status = JobStatus.PROCESSING
        db.commit()

        for cert in job.certificates:
            _process_certificate(db, job, cert)

        job.status = (
            JobStatus.COMPLETED if job.failed == 0 else JobStatus.COMPLETED_WITH_ERRORS
        )
        db.commit()
    except Exception:  # pragma: no cover - defensive; a crash in the loop above
        logger.exception("process_job: unexpected failure for job %s", job_id)
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            db.commit()
    finally:
        db.close()


def _process_certificate(db, job: Job, cert: Certificate) -> None:
    """Generate a single certificate; record success/failure on its row.

    Any exception is caught and stored on the certificate so that it never
    aborts the rest of the batch.
    """
    try:
        validate_recipient(cert.recipient_name, cert.recipient_email)
        path = render_certificate(
            cert_id=cert.id,
            recipient_name=cert.recipient_name.strip(),
            course_name=job.course_name,
            issuer=job.issuer,
            issue_date=job.issue_date,
        )
        cert.status = CertificateStatus.SUCCESS
        cert.file_path = str(path)
        cert.error_message = None
        job.succeeded += 1
    except Exception as exc:
        cert.status = CertificateStatus.FAILED
        cert.error_message = str(exc)
        job.failed += 1
        logger.warning(
            "certificate %s (row %s) failed: %s", cert.id, cert.row_index, exc
        )
    finally:
        # Commit per-certificate so progress is visible while the job runs.
        db.commit()
