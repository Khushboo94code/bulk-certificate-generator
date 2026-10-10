"""FastAPI application: HTTP layer for the bulk certificate generator."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import crud
from app.config import PROCESS_SYNC
from app.database import get_db, init_db
from app.models import Certificate, CertificateStatus, Job
from app.schemas import CertificateOut, JobCreate, JobDetail, JobSummary
from app.worker import process_job, submit_job

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Bulk Certificate Generator",
    description="Submit a batch of recipients and generate certificates for each.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---- Serialization helpers -------------------------------------------------


def _cert_to_out(cert: Certificate) -> CertificateOut:
    download_url = (
        f"/certificates/{cert.id}/download"
        if cert.status == CertificateStatus.SUCCESS
        else None
    )
    return CertificateOut(
        id=cert.id,
        row_index=cert.row_index,
        recipient_name=cert.recipient_name,
        recipient_email=cert.recipient_email,
        status=cert.status.value,
        error_message=cert.error_message,
        download_url=download_url,
    )


def _job_summary(job: Job) -> JobSummary:
    return JobSummary(
        id=job.id,
        course_name=job.course_name,
        issuer=job.issuer,
        issue_date=job.issue_date,
        status=job.status.value,
        total=job.total,
        succeeded=job.succeeded,
        failed=job.failed,
        pending=crud.pending_count(job),
    )


# ---- Routes ----------------------------------------------------------------


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the single-page UI."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/jobs", response_model=JobSummary, status_code=status.HTTP_202_ACCEPTED)
def create_job(payload: JobCreate, db: Session = Depends(get_db)) -> JobSummary:
    """Accept a bulk certificate request and start generation.

    Returns ``202 Accepted`` with a job id; generation runs in the background
    (or inline when ``CERT_PROCESS_SYNC`` is enabled, used by tests).
    """
    job = crud.create_job(db, payload)
    job_id = job.id

    if PROCESS_SYNC:
        process_job(job_id)
        db.expire_all()
        job = crud.get_job(db, job_id)
    else:
        submit_job(job_id)

    return _job_summary(job)


@app.get("/jobs/{job_id}", response_model=JobDetail)
def get_job_status(job_id: str, db: Session = Depends(get_db)) -> JobDetail:
    """Return job progress plus the status of every certificate in it."""
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    summary = _job_summary(job)
    return JobDetail(
        **summary.model_dump(),
        certificates=[_cert_to_out(c) for c in job.certificates],
    )


@app.get("/jobs/{job_id}/certificates", response_model=list[CertificateOut])
def list_job_certificates(
    job_id: str,
    status_filter: str | None = None,
    db: Session = Depends(get_db),
) -> list[CertificateOut]:
    """List certificates for a job, optionally filtered by status.

    ``status_filter`` accepts one of: pending, success, failed.
    """
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    certs = job.certificates
    if status_filter is not None:
        try:
            wanted = CertificateStatus(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="status_filter must be one of: pending, success, failed",
            )
        certs = [c for c in certs if c.status == wanted]

    return [_cert_to_out(c) for c in certs]


@app.get("/certificates/{cert_id}", response_model=CertificateOut)
def get_certificate(cert_id: str, db: Session = Depends(get_db)) -> CertificateOut:
    cert = crud.get_certificate(db, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="certificate not found")
    return _cert_to_out(cert)


@app.get("/certificates/{cert_id}/download")
def download_certificate(cert_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """Download the generated certificate PDF."""
    cert = crud.get_certificate(db, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="certificate not found")
    if cert.status != CertificateStatus.SUCCESS or not cert.file_path:
        raise HTTPException(
            status_code=409,
            detail=f"certificate is not available (status: {cert.status.value})",
        )
    if not Path(cert.file_path).exists():
        raise HTTPException(status_code=410, detail="certificate file is missing")

    safe_name = cert.recipient_name.strip().replace(" ", "_") or "certificate"
    return FileResponse(
        cert.file_path,
        media_type="application/pdf",
        filename=f"{safe_name}_certificate.pdf",
    )
