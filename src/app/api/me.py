from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.auth import get_current_user, User

router = APIRouter()

class MeResponse(BaseModel):
    sub: str
    email: str | None = None
    role: str | None = None
    aal: str | None = None

@router.get("/me", response_model=MeResponse, tags=["me"])
async def me(current_user: User = Depends(get_current_user)):
    return MeResponse(**current_user.dict())
