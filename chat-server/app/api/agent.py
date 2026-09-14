from typing import Annotated
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from langchain_core.messages import BaseMessage

from app.schemas.chat import ChatMessage, ChatRequest, ChatResponse, HistoryResponse
from app.services import dashscope


router = APIRouter()


def serialize_message(message: BaseMessage) -> ChatMessage:
    role = "assistant" if message.type == "ai" else "user"
    return ChatMessage(role=role, content=str(message.content))


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    config = {"configurable": {"thread_id": payload.thread_id}}
    try:
        result = await request.app.state.chat_graph.ainvoke(
            {"current_message": payload.message},
            config=config,
        )
    except dashscope.DashScopeError as exc:
        logging.warning(
            "DashScope call failed: code=%s status_code=%s",
            exc.code,
            exc.status_code,
        )
        raise HTTPException(
            status_code=502,
            detail=f"DashScope call failed: {exc.code}: {exc.message}",
        ) from exc

    message = serialize_message(result["messages"][-1])
    return ChatResponse(thread_id=payload.thread_id, message=message)


@router.get("/history", response_model=HistoryResponse)
async def history(
    request: Request,
    thread_id: Annotated[str, Query(min_length=1)],
) -> HistoryResponse:
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await request.app.state.chat_graph.aget_state(config)
    messages = snapshot.values.get("messages", [])
    return HistoryResponse(
        thread_id=thread_id,
        messages=[serialize_message(message) for message in messages],
    )
