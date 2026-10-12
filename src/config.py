import os


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", "./data/vector_store")
    HR_EMAIL = os.getenv("HR_EMAIL", "hr@example.com")
    HR_PASSWORD = os.getenv("HR_PASSWORD", "changeme")
    CANDIDATE_EMAIL = os.getenv("CANDIDATE_EMAIL", "candidate@example.com")
    CANDIDATE_PASSWORD = os.getenv("CANDIDATE_PASSWORD", "changeme")
