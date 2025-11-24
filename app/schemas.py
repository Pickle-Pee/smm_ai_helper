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
