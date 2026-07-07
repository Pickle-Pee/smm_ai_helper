from app.services.task_pipeline import TaskPipelineService

# Backward-compatible alias.
# New code should import TaskPipelineService from app.services.task_pipeline.
OrchestratorService = TaskPipelineService

__all__ = ["OrchestratorService", "TaskPipelineService"]
