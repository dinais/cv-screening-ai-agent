import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    # ODBC connection string for SQL Server (Somee). Blank uses local SQLite.
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", "./data/vector_store")
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.2")
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
    HR_EMAIL = os.getenv("HR_EMAIL", "hr@example.com")
    HR_PASSWORD = os.getenv("HR_PASSWORD", "changeme")
    CANDIDATE_EMAIL = os.getenv("CANDIDATE_EMAIL", "candidate@example.com")
    CANDIDATE_PASSWORD = os.getenv("CANDIDATE_PASSWORD", "changeme")
    # More mock candidates, as email:password pairs separated by commas.
    EXTRA_CANDIDATES = os.getenv("EXTRA_CANDIDATES", "")
