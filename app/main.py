from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.sales import generate_sales_reply


app = FastAPI(
    title=settings.app_name,
    description="AI sales automation platform",
    version="0.1.0",
)


class SalesRequest(BaseModel):
    customer_message: str
    product_context: str = ""


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


@app.post("/sales/reply")
def sales_reply(request: SalesRequest):
    try:
        reply = generate_sales_reply(
            customer_message=request.customer_message,
            product_context=request.product_context,
        )

        return {
            "success": True,
            "reply": reply,
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )
