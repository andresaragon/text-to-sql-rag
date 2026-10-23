import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
    )
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "sqlcoder")
    embedding_model: str = os.getenv(
        "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    max_rows_returned: int = int(os.getenv("MAX_ROWS_RETURNED", "100"))
    query_timeout_seconds: int = int(os.getenv("QUERY_TIMEOUT_SECONDS", "5"))
    max_question_chars: int = int(os.getenv("MAX_QUESTION_CHARS", "500"))
    allowed_schema: str = os.getenv("ALLOWED_SCHEMA", "public")

    db_pool_size: int = int(os.getenv("DB_POOL_SIZE", "5"))
    db_max_overflow: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    db_pool_timeout_seconds: int = int(os.getenv("DB_POOL_TIMEOUT_SECONDS", "10"))
    db_connect_timeout_seconds: int = int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "3"))
    max_schema_distance: float = float(os.getenv("MAX_SCHEMA_DISTANCE", "0.7"))
    warmup_on_startup: bool = os.getenv("WARMUP_ON_STARTUP", "true").strip().lower() not in ("false", "0")


settings = Settings()
