"""End-to-end API tests covering every required area."""
from pathlib import Path


def _create(client, payload):
    resp = client.post("/jobs", json=payload)
    return resp


# ---- UI --------------------------------------------------------------------


def test_index_serves_ui(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Bulk Certificate Generator" in resp.text


# ---- Creating a generation job --------------------------------------------


def test_create_job_returns_accepted_with_job_id(client, sample_payload):
    resp = _create(client, sample_payload)
    assert resp.status_code == 202
    body = resp.json()
    assert body["id"]
    assert body["total"] == 2
    assert body["course_name"] == "Introduction to Python"


def test_issue_date_defaults_to_today_when_omitted(client, sample_payload):
    sample_payload.pop("issue_date")
    resp = _create(client, sample_payload)
    assert resp.status_code == 202
    assert resp.json()["issue_date"]  # non-empty ISO date


# ---- Input validation ------------------------------------------------------


def test_missing_course_name_is_rejected(client, sample_payload):
    sample_payload.pop("course_name")
    resp = _create(client, sample_payload)
    assert resp.status_code == 422


def test_empty_recipient_list_is_rejected(client, sample_payload):
    sample_payload["recipients"] = []
    resp = _create(client, sample_payload)
    assert resp.status_code == 422


def test_too_many_recipients_is_rejected(client, sample_payload, monkeypatch):
    # Exceed the configured cap (default 10000) cheaply by patching the schema.
    from app import schemas

    monkeypatch.setattr(schemas, "MAX_RECIPIENTS_PER_JOB", 1)
    sample_payload["recipients"] = [
        {"name": "A"},
        {"name": "B"},
    ]
    resp = _create(client, sample_payload)
    assert resp.status_code == 422


# ---- Certificate generation ------------------------------------------------


def test_certificates_are_generated_as_pdfs(client, sample_payload):
    job_id = _create(client, sample_payload).json()["id"]
    detail = client.get(f"/jobs/{job_id}").json()

    assert detail["succeeded"] == 2
    for cert in detail["certificates"]:
        assert cert["status"] == "success"
        # Download and confirm it's a real PDF.
        dl = client.get(cert["download_url"])
        assert dl.status_code == 200
        assert dl.headers["content-type"] == "application/pdf"
        assert dl.content.startswith(b"%PDF")


# ---- Job status / progress -------------------------------------------------


def test_job_status_reports_counts(client, sample_payload):
    job_id = _create(client, sample_payload).json()["id"]
    detail = client.get(f"/jobs/{job_id}").json()

    assert detail["status"] == "completed"
    assert detail["total"] == 2
    assert detail["succeeded"] == 2
    assert detail["failed"] == 0
    assert detail["pending"] == 0
    assert len(detail["certificates"]) == 2


def test_unknown_job_returns_404(client):
    assert client.get("/jobs/does-not-exist").status_code == 404


# ---- Handling an individual certificate failure ----------------------------


def test_invalid_recipient_fails_without_blocking_others(client, sample_payload):
    # One recipient with a blank name (invalid) and one bad email among valids.
    sample_payload["recipients"] = [
        {"name": "Valid Person", "email": "valid@example.com"},
        {"name": "   ", "email": "whoever@example.com"},   # blank name -> fail
        {"name": "Bad Email", "email": "not-an-email"},      # bad email -> fail
        {"name": "Another Valid"},
    ]
    job_id = _create(client, sample_payload).json()["id"]
    detail = client.get(f"/jobs/{job_id}").json()

    assert detail["status"] == "completed_with_errors"
    assert detail["total"] == 4
    assert detail["succeeded"] == 2
    assert detail["failed"] == 2

    by_row = {c["row_index"]: c for c in detail["certificates"]}
    assert by_row[0]["status"] == "success"
    assert by_row[1]["status"] == "failed"
    assert "name is required" in by_row[1]["error_message"]
    assert by_row[2]["status"] == "failed"
    assert "invalid email" in by_row[2]["error_message"]
    assert by_row[3]["status"] == "success"


def test_generation_error_is_isolated(client, sample_payload, monkeypatch):
    """If the renderer raises for one recipient, others still succeed."""
    from app import worker

    real_render = worker.render_certificate

    def flaky_render(*, recipient_name, **kwargs):
        if recipient_name == "Bob Jones":
            raise RuntimeError("boom: simulated rendering failure")
        return real_render(recipient_name=recipient_name, **kwargs)

    monkeypatch.setattr(worker, "render_certificate", flaky_render)

    job_id = _create(client, sample_payload).json()["id"]
    detail = client.get(f"/jobs/{job_id}").json()

    assert detail["succeeded"] == 1
    assert detail["failed"] == 1
    failed = [c for c in detail["certificates"] if c["status"] == "failed"][0]
    assert failed["recipient_name"] == "Bob Jones"
    assert "boom" in failed["error_message"]


# ---- Retrieving generated certificates -------------------------------------


def test_list_certificates_with_status_filter(client, sample_payload):
    sample_payload["recipients"] = [
        {"name": "Good One"},
        {"name": ""},  # invalid -> failed
    ]
    job_id = _create(client, sample_payload).json()["id"]

    all_certs = client.get(f"/jobs/{job_id}/certificates").json()
    assert len(all_certs) == 2

    only_failed = client.get(
        f"/jobs/{job_id}/certificates", params={"status_filter": "failed"}
    ).json()
    assert len(only_failed) == 1
    assert only_failed[0]["status"] == "failed"

    only_success = client.get(
        f"/jobs/{job_id}/certificates", params={"status_filter": "success"}
    ).json()
    assert len(only_success) == 1


def test_bad_status_filter_rejected(client, sample_payload):
    job_id = _create(client, sample_payload).json()["id"]
    resp = client.get(
        f"/jobs/{job_id}/certificates", params={"status_filter": "nonsense"}
    )
    assert resp.status_code == 400


def test_download_failed_certificate_returns_conflict(client, sample_payload):
    sample_payload["recipients"] = [{"name": ""}]  # will fail
    job_id = _create(client, sample_payload).json()["id"]
    cert = client.get(f"/jobs/{job_id}/certificates").json()[0]
    resp = client.get(f"/certificates/{cert['id']}/download")
    assert resp.status_code == 409


def test_single_certificate_lookup(client, sample_payload):
    job_id = _create(client, sample_payload).json()["id"]
    cert = client.get(f"/jobs/{job_id}/certificates").json()[0]
    resp = client.get(f"/certificates/{cert['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == cert["id"]
