from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    name: str | None = None


class ChatResponse(BaseModel):
    thread_id: str
    message: ChatMessage


class HistoryResponse(BaseModel):
    thread_id: str
    messages: list[ChatMessage]


class GroupMember(BaseModel):
    name: str = Field(min_length=1)
    persona: str = ""


class GroupChatRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    group_intro: str = ""
    user_persona: str = ""
    members: list[GroupMember] = Field(default_factory=list)
    max_rounds: int = Field(default=5, ge=1, le=100)


class GroupChatResponse(BaseModel):
    thread_id: str
    messages: list[ChatMessage]
