from __future__ import annotations

from typing import Any, Dict

from app.services.image_orchestrator import ImageOrchestrator
from app.services.task_session_service import TaskSessionState


class TaskImageService:
    """Builds image output for task pipeline sessions."""

    def __init__(self) -> None:
        self.image_orchestrator = ImageOrchestrator()

    async def generate_for_task_session(
        self,
        session_state: TaskSessionState,
    ) -> Dict[str, Any] | None:
        if session_state.mode not in {"image", "text+image"}:
            return None

        answers = session_state.answers or {}
        return await self.image_orchestrator.generate(
            platform=answers.get("platform", "auto"),
            use_case=answers.get("use_case", "auto"),
            message=session_state.task_description,
            brand=answers.get("brand"),
            overlay=answers.get("overlay"),
            variants=int(answers.get("variants", 1) or 1),
            user_id=session_state.user_id,
            request_id=session_state.request_id,
        )
