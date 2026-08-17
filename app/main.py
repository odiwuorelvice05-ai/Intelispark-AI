from fastapi import FastAPI
from app.config import settings

app = FastAPI(
    title=settings.app_name,
    description="AI sales automation platform",
    version="0.1.0",
)


@app.get("/")
def root():
    return {
        "name": settings.app_name,
        "status": "online",
        "version": "0.1.0",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "environment": settings.environment,
    }
