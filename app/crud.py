"""Database access helpers, kept separate from the HTTP layer."""
from datetime import date

from sqlalchemy.orm import Session

from app.models import Certificate, CertificateStatus, Job
from app.schemas import JobCreate


def create_job(db: Session, payload: JobCreate) -> Job:
    """Persist a job and one pending certificate row per recipient."""
    issue_date = (payload.issue_date or date.today()).isoformat()

    job = Job(
        course_name=payload.course_name.strip(),
        issuer=payload.issuer.strip(),
        issue_date=issue_date,
        total=len(payload.recipients),
    )
    for idx, recipient in enumerate(payload.recipients):
        job.certificates.append(
            Certificate(
                row_index=idx,
                recipient_name=recipient.name,
                recipient_email=recipient.email,
                status=CertificateStatus.PENDING,
            )
        )

    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: str) -> Job | None:
    return db.get(Job, job_id)


def get_certificate(db: Session, cert_id: str) -> Certificate | None:
    return db.get(Certificate, cert_id)


def pending_count(job: Job) -> int:
    return job.total - job.succeeded - job.failed
