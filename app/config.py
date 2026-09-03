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


settings = Settings()
