from fastapi import FastAPI

from app.routers.documents import router as documents_router

app = FastAPI(title="KnowFlow AI API")
app.include_router(documents_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
