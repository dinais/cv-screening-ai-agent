from io import BytesIO

from src import create_app
from src.commands.job_commands import CreateJobCommand
from src.cv_pdf import PdfError, extract_pdf_text, readable_cv_text
from tests.pdf_samples import pdf_bytes, pdf_upload
from tests.test_auth import TestConfig


class _Upload:
    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self._data = data

    def read(self) -> bytes:
        return self._data


def test_a_pdf_that_splits_every_word_is_joined_into_a_sentence():
    raw = "\n \n".join(["B.Sc.", "in", "Computer", "Science.", "Tailwind", "CSS."])
    assert readable_cv_text(raw) == "B.Sc. in Computer Science. Tailwind CSS."


def test_pdf_text_is_extracted_and_other_files_are_rejected():
    text, data = extract_pdf_text(_Upload("cv.pdf", pdf_bytes("Python and Flask")))
    assert "Python and Flask" in text
    assert data.startswith(b"%PDF")
    try:
        extract_pdf_text(_Upload("cv.txt", b"plain text"))
    except PdfError as exc:
        assert "PDF" in str(exc)
    else:
        raise AssertionError("a text file was accepted")
    try:
        extract_pdf_text(None)
    except PdfError as exc:
        assert "required" in str(exc).lower()
    else:
        raise AssertionError("a missing file was accepted")


def test_apply_requires_a_pdf_and_hr_can_open_it():
    app = create_app(TestConfig)
    store = app.extensions["event_store"]
    job = CreateJobCommand(store).execute(
        title="Backend engineer", requirements="Python", created_by="hr@example.com"
    )
    candidate = app.test_client()
    candidate.post("/login", data={"email": "candidate@example.com", "password": "candidate-pass"})

    missing = candidate.post(f"/apply/{job.reference_id}", data={"full_name": "Ada Lovelace"})
    assert b"A CV PDF is required." in missing.data
    assert store.load_by_types(("ApplicationSubmitted",)) == []

    form = candidate.get(f"/apply/{job.reference_id}")
    assert b'required' in form.data
    assert b'type="file"' in form.data

    submitted = candidate.post(
        f"/apply/{job.reference_id}",
        data={"full_name": "Ada Lovelace", **pdf_upload("Analytical engines.")},
        follow_redirects=True,
    )
    assert b"Application submitted." in submitted.data
    application_id = store.load_by_types(("ApplicationSubmitted",))[0].payload["application_id"]
    assert "Analytical engines." in store.load(application_id)[0].payload["cv_text"]

    hr = app.test_client()
    hr.post("/login", data={"email": "hr@example.com", "password": "hr-pass"})
    page = hr.get(f"/hr/applications/{application_id}")
    assert b"Open PDF" in page.data
    assert b"Analytical engines." not in page.data
    opened = hr.get(f"/hr/applications/{application_id}/cv")
    assert opened.status_code == 200
    assert opened.mimetype == "application/pdf"
    assert opened.data.startswith(b"%PDF")

    denied = candidate.get(f"/hr/applications/{application_id}/cv")
    assert denied.status_code == 403


def test_a_non_pdf_upload_does_not_append():
    app = create_app(TestConfig)
    store = app.extensions["event_store"]
    job = CreateJobCommand(store).execute(
        title="Backend engineer", requirements="Python", created_by="hr@example.com"
    )
    candidate = app.test_client()
    candidate.post("/login", data={"email": "candidate@example.com", "password": "candidate-pass"})
    response = candidate.post(
        f"/apply/{job.reference_id}",
        data={"full_name": "Ada Lovelace", "cv": (BytesIO(b"not a pdf"), "notes.pdf")},
        content_type="multipart/form-data",
    )
    assert b"The CV must be a PDF file." in response.data
    assert store.load_by_types(("ApplicationSubmitted",)) == []
