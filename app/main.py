from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(
    title="Text-to-SQL Assistant with RAG",
    description="Traduce preguntas en lenguaje natural a SQL seguro, "
    "usando RAG para dar contexto del esquema real de la base de datos.",
    version="0.1.0",
)

app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
