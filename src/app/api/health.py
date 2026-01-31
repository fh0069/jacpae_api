from fastapi import APIRouter
from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: str = "ok"

router = APIRouter()

@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health():
    return HealthResponse()
