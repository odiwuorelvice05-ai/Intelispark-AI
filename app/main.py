from fastapi import FastAPI

app = FastAPI(
    title="Forge AI",
    description="AI sales automation platform",
    version="0.1.0",
)


@app.get("/")
def root():
    return {
        "name": "Forge AI",
        "status": "online",
        "version": "0.1.0",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
    }
