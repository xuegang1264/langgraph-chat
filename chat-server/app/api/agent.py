from collections.abc import AsyncIterator
import json
from typing import Annotated
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agent.mainGraph.node.main_chat import build_main_chat_model_messages
from app.core.config import settings

from app.schemas.chat import (
    ChatMessage,
    ChatRequest,
    GroupChatRequest,
    GroupChatResponse,
    HistoryResponse,
)
from app.services import dashscope


router = APIRouter()
group_chat_router = APIRouter()


def group_chat_input(payload: GroupChatRequest) -> dict:
    return {
        "current_message": payload.message,
        "group_intro": payload.group_intro,
        "user_persona": payload.user_persona,
        "members": [member.model_dump() for member in payload.members],
        "tool_results": {},
        "next_role": None,
        "should_end": False,
        "round_count": 0,
        "max_rounds": payload.max_rounds,
    }


def encode_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def serialize_message(message: BaseMessage) -> ChatMessage:
    role = "assistant" if message.type == "ai" else "user"
    return ChatMessage(
        role=role,
        content=str(message.content),
        name=getattr(message, "name", None),
    )


async def stream_chat_events(
    payload: ChatRequest,
    request: Request,
) -> AsyncIterator[str]:
    config = {"configurable": {"thread_id": payload.thread_id}}
    try:
        snapshot = await request.app.state.chat_graph.aget_state(config)
        current_message = payload.message.strip()
        user_message = HumanMessage(content=current_message)

        if not settings.dashscope_api_key:
            await request.app.state.chat_graph.aupdate_state(
                config,
                {"messages": [user_message]},
                as_node="chat",
            )
            yield encode_sse("done", {"thread_id": payload.thread_id})
            return

        model_messages = build_main_chat_model_messages(
            snapshot.values,
            current_message,
        )
        content_parts: list[str] = []
        async for token in dashscope.chat_stream(
            thread_id=payload.thread_id,
            messages=model_messages,
            model=settings.dashscope_model,
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        ):
            content_parts.append(token)
            yield encode_sse("token", {"token": token})

        content = dashscope.clean_model_content("".join(content_parts))
        assistant_message = AIMessage(content=content)
        await request.app.state.chat_graph.aupdate_state(
            config,
            {"messages": [user_message, assistant_message]},
            as_node="chat",
        )
        yield encode_sse(
            "message",
            serialize_message(assistant_message).model_dump(exclude_none=True),
        )
        yield encode_sse("done", {"thread_id": payload.thread_id})
    except dashscope.DashScopeError as exc:
        logging.warning(
            "DashScope stream call failed: code=%s status_code=%s",
            exc.code,
            exc.status_code,
        )
        yield encode_sse(
            "error",
            {
                "detail": f"DashScope call failed: {exc.code}: {exc.message}",
            },
        )
    except Exception as exc:
        logging.exception("Chat stream failed unexpectedly")
        yield encode_sse(
            "error",
            {
                "detail": f"Chat stream failed: {exc}",
            },
        )


@router.post("/chat")
async def chat(payload: ChatRequest, request: Request) -> StreamingResponse:
    return StreamingResponse(
        stream_chat_events(payload, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.get(
    "/history",
    response_model=HistoryResponse,
    response_model_exclude_none=True,
)
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


@router.delete("/history")
async def delete_history(
    request: Request,
    thread_id: Annotated[str, Query(min_length=1)],
) -> dict[str, str]:
    await request.app.state.checkpointer.adelete_thread(thread_id)
    return {"thread_id": thread_id}


@group_chat_router.post(
    "/chat",
    response_model=GroupChatResponse,
    response_model_exclude_none=True,
)
async def group_chat(payload: GroupChatRequest, request: Request) -> GroupChatResponse:
    config = {"configurable": {"thread_id": payload.thread_id}}
    snapshot = await request.app.state.group_chat_graph.aget_state(config)
    previous_count = len(snapshot.values.get("messages", []))

    try:
        result = await request.app.state.group_chat_graph.ainvoke(
            group_chat_input(payload),
            config=config,
        )
    except dashscope.DashScopeError as exc:
        logging.warning(
            "Group chat DashScope call failed: code=%s status_code=%s",
            exc.code,
            exc.status_code,
        )
        raise HTTPException(
            status_code=502,
            detail=f"DashScope call failed: {exc.code}: {exc.message}",
        ) from exc

    new_messages = result["messages"][previous_count:]
    assistant_messages = [
        serialize_message(message)
        for message in new_messages
        if message.type == "ai"
    ]
    return GroupChatResponse(thread_id=payload.thread_id, messages=assistant_messages)


async def stream_group_chat_events(
    payload: GroupChatRequest,
    request: Request,
) -> AsyncIterator[str]:
    config = {"configurable": {"thread_id": payload.thread_id}}

    try:
        async for update in request.app.state.group_chat_graph.astream(
            group_chat_input(payload),
            config=config,
            stream_mode="updates",
        ):
            for node_update in update.values():
                for message in node_update.get("messages", []):
                    if message.type != "ai":
                        continue

                    yield encode_sse(
                        "message",
                        serialize_message(message).model_dump(exclude_none=True),
                    )

        yield encode_sse("done", {"thread_id": payload.thread_id})
    except dashscope.DashScopeError as exc:
        logging.warning(
            "Group chat stream DashScope call failed: code=%s status_code=%s",
            exc.code,
            exc.status_code,
        )
        yield encode_sse(
            "error",
            {
                "detail": f"DashScope call failed: {exc.code}: {exc.message}",
            },
        )


@group_chat_router.post("/chat/stream")
async def stream_group_chat(
    payload: GroupChatRequest,
    request: Request,
) -> StreamingResponse:
    return StreamingResponse(
        stream_group_chat_events(payload, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@group_chat_router.get(
    "/history",
    response_model=HistoryResponse,
    response_model_exclude_none=True,
)
async def group_history(
    request: Request,
    thread_id: Annotated[str, Query(min_length=1)],
) -> HistoryResponse:
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await request.app.state.group_chat_graph.aget_state(config)
    messages = snapshot.values.get("messages", [])
    return HistoryResponse(
        thread_id=thread_id,
        messages=[serialize_message(message) for message in messages],
    )


@group_chat_router.delete("/history")
async def delete_group_history(
    request: Request,
    thread_id: Annotated[str, Query(min_length=1)],
) -> dict[str, str]:
    await request.app.state.checkpointer.adelete_thread(thread_id)
    return {"thread_id": thread_id}
