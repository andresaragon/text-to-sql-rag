import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
    )
    target_database_url: str = (
        os.getenv("TARGET_DATABASE_URL")
        if os.getenv("TARGET_DATABASE_URL") and os.getenv("TARGET_DATABASE_URL").strip()
        else database_url
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
    _target_dialect: str = os.getenv("TARGET_DIALECT", "postgres")

    @property
    def target_dialect(self) -> str:
        val = getattr(self, "_target_dialect", "postgres")
        return val.strip().lower() if val else "postgres"

    @target_dialect.setter
    def target_dialect(self, value: str) -> None:
        self._target_dialect = value

    db_pool_size: int = int(os.getenv("DB_POOL_SIZE", "5"))
    db_max_overflow: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    db_pool_timeout_seconds: int = int(os.getenv("DB_POOL_TIMEOUT_SECONDS", "10"))
    db_connect_timeout_seconds: int = int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "3"))
    max_schema_distance: float = float(os.getenv("MAX_SCHEMA_DISTANCE", "0.7"))
    warmup_on_startup: bool = os.getenv("WARMUP_ON_STARTUP", "true").strip().lower() not in ("false", "0")


settings = Settings()
