from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.api.routes import router
from app.config import settings
from app.core.embeddings import _get_model


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.warmup_on_startup:
        _get_model()
    yield


app = FastAPI(
    title="Text-to-SQL Assistant with RAG",
    description="Traduce preguntas en lenguaje natural a SQL seguro, "
    "usando RAG para dar contexto del esquema real de la base de datos.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
