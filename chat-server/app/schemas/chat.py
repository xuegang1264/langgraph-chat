from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatResponse(BaseModel):
    thread_id: str
    message: ChatMessage


class HistoryResponse(BaseModel):
    thread_id: str
    messages: list[ChatMessage]
