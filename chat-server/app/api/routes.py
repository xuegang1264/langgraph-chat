from fastapi import APIRouter

from app.api.agent import group_chat_router, router as agent_router


router = APIRouter()
router.include_router(agent_router, prefix="/agent", tags=["agent"])
router.include_router(group_chat_router, prefix="/group-chat", tags=["group-chat"])


@router.get("/")
async def root() -> dict[str, str]:
    return {"service": "chat-server", "status": "running"}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
