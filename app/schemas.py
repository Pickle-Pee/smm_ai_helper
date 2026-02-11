# app/schemas.py
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class UserCreate(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class UserRead(UserCreate):
    id: int

    class Config:
        from_attributes = True


class AgentRunRequest(BaseModel):
    user: Optional[UserCreate] = None
    agent_type: str
    task_description: str
    answers: Dict[str, Any]


class AgentRunResponse(BaseModel):
    task_id: int
    agent_type: str
    status: str
    result: Dict[str, Any]


class TaskRead(BaseModel):
    id: int
    agent_type: str
    task_description: str
    answers: Dict[str, Any] | None
    result: Dict[str, Any] | None
    status: str
    error: Optional[str] = None

    class Config:
        from_attributes = True


class TaskShort(BaseModel):
    id: int
    agent_type: str
    task_description: str
    created_at: str

    class Config:
        from_attributes = True


class TaskStartRequest(BaseModel):
    user: Optional[UserCreate] = None
    agent_type: str
    task_description: str
    answers: Dict[str, Any] = {}
    mode: str = "text"


class TaskAnswerRequest(BaseModel):
    session_id: str
    key: str
    value: str


class TaskNeedInfoResponse(BaseModel):
    status: str
    session_id: str
    questions: List[Dict[str, str]]


class TaskDoneResponse(BaseModel):
    status: str
    session_id: str
    result: Dict[str, Any]
    image: Dict[str, Any] | None = None


class ImageGenerateRequest(BaseModel):
    platform: str = "auto"
    use_case: str = "auto"
    message: str
    brand: Dict[str, Any] | None = None
    overlay: Dict[str, str] | None = None
    variants: int = 1


class ImageGenerateResponse(BaseModel):
    status: str
    mode: str
    preset_id: str
    images: List[Dict[str, str]]


class ChatMessageRequest(BaseModel):
    user_id: str
    text: str
    attachments: List[Dict[str, Any]] = []


class ChatMessageResponse(BaseModel):
    reply: str
    follow_up_question: str | None
    actions: List[Dict[str, str]]
    debug: Dict[str, Any]
    image: Dict[str, Any] | None = None
