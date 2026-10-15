from src import create_app


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    HR_EMAIL = "hr@example.com"
    HR_PASSWORD = "hr-pass"
    CANDIDATE_EMAIL = "candidate@example.com"
    CANDIDATE_PASSWORD = "candidate-pass"
    DATABASE_URL = "sqlite:///:memory:"
    OPENAI_API_KEY = ""
    VECTOR_DB_PATH = "./data/vector_store"
    LLM_PROVIDER = "mock"


def _client():
    app = create_app(TestConfig)
    return app.test_client()


def test_extra_candidates_can_log_in():
    class Config(TestConfig):
        EXTRA_CANDIDATES = "maya.cohen@example.com:maya-pass,omar.nasser@example.com:omar-pass"

    client = create_app(Config).test_client()
    response = client.post(
        "/login",
        data={"email": "omar.nasser@example.com", "password": "omar-pass"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Apply" in response.data or b"open" in response.data.lower()


def test_hr_login_reaches_dashboard():
    client = _client()
    response = client.post(
        "/login",
        data={"email": "hr@example.com", "password": "hr-pass"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Hiring dashboard" in response.data


def test_candidate_login_reaches_application_view():
    client = _client()
    response = client.post(
        "/login",
        data={"email": "candidate@example.com", "password": "candidate-pass"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Submit an application" in response.data


def test_unauthenticated_hr_route_redirects_to_login():
    client = _client()
    response = client.get("/hr/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_candidate_cannot_access_hr_portal():
    client = _client()
    client.post("/login", data={"email": "candidate@example.com", "password": "candidate-pass"})
    response = client.get("/hr/")
    assert response.status_code == 403
