"""Pydantic request/response models (API contract + input validation)."""
import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import MAX_RECIPIENTS_PER_JOB

# Simple, permissive email pattern. Good enough to reject obvious garbage
# without pulling in a full email-validation dependency.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RecipientIn(BaseModel):
    """A single recipient as submitted by the client.

    Note: semantic validation (empty name, bad email) is intentionally *not*
    enforced here. We accept the shape at the API boundary and validate each
    recipient during generation so that one bad recipient is recorded as a
    failed certificate instead of rejecting the entire batch.
    """

    name: str
    email: str | None = None


class JobCreate(BaseModel):
    course_name: str = Field(..., min_length=1, max_length=255)
    issuer: str = Field(..., min_length=1, max_length=255)
    # Defaults to today if the client omits it.
    issue_date: date | None = None
    recipients: list[RecipientIn] = Field(..., min_length=1)

    @field_validator("recipients")
    @classmethod
    def _cap_recipients(cls, v: list[RecipientIn]) -> list[RecipientIn]:
        if len(v) > MAX_RECIPIENTS_PER_JOB:
            raise ValueError(
                f"too many recipients: {len(v)} (max {MAX_RECIPIENTS_PER_JOB})"
            )
        return v


# ---- Response models -------------------------------------------------------


class CertificateOut(BaseModel):
    id: str
    row_index: int
    recipient_name: str
    recipient_email: str | None
    status: str
    error_message: str | None
    # Convenience download link, populated for successfully generated certs.
    download_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class JobSummary(BaseModel):
    id: str
    course_name: str
    issuer: str
    issue_date: str
    status: str
    total: int
    succeeded: int
    failed: int
    pending: int

    model_config = ConfigDict(from_attributes=True)


class JobDetail(JobSummary):
    certificates: list[CertificateOut]


def validate_recipient(name: str, email: str | None) -> None:
    """Semantic validation applied per-recipient at generation time.

    Raises ``ValueError`` with a human-readable reason on invalid input.
    """
    if not name or not name.strip():
        raise ValueError("recipient name is required")
    if len(name) > 255:
        raise ValueError("recipient name too long (max 255 chars)")
    if email is not None and email.strip() and not _EMAIL_RE.match(email):
        raise ValueError(f"invalid email address: {email!r}")
