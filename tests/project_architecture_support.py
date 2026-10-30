"""Exact import permissions for the saved-project contour.

These adapters can share typed errors/contracts or read accepted sources. They do
not grant graph execution capabilities to Telegram, legacy routes or workers.
"""
import ast

PROJECT_COPILOT_IMPORTS = {
    "app/routers/projects.py": {
        "app.marketing_copilot.api_contracts.ErrorResponse", "app.marketing_copilot.api_contracts.StrictDTO"},
    "app/routers/chat_router.py": {"app.marketing_copilot.api_errors.CopilotAPIError"},
    "app/services/chat_memory_service.py": {"app.marketing_copilot.api_errors.CopilotAPIError"},
    "app/services/chat_execution_service.py": {
        "app.marketing_copilot.api_contracts.StrictDTO", "app.marketing_copilot.api_errors.CopilotAPIError",
        "app.marketing_copilot.api_errors.ProviderUnavailable", "app.marketing_copilot.provider_adapters.expected_provider_failure",
        "app.marketing_copilot.execution_store.ExecutionStore"},
    "app/services/project_context_service.py": {
        "app.marketing_copilot.api_contracts.StrictDTO", "app.marketing_copilot.api_errors.CopilotAPIError",
        "app.marketing_copilot.api_errors.ProviderUnavailable", "app.marketing_copilot.mentor_contracts.MentorAnswer",
        "app.marketing_copilot.mentor_contracts.MentorQuestion", "app.marketing_copilot.provider_adapters.application_model_call",
        "app.marketing_copilot.provider_adapters.expected_provider_failure",
        "app.marketing_copilot.execution_store.ExecutionStore"},
    "app/services/project_history_service.py": {
        "app.marketing_copilot.api_errors.CopilotAPIError", "app.marketing_copilot.api_errors.ProviderUnavailable",
        "app.marketing_copilot.execution_store.RESPONSE", "app.marketing_copilot.execution_store.RETENTION",
        "app.marketing_copilot.execution_store.WORKFLOW_TYPE", "app.marketing_copilot.mentor.COMPANION_TYPE",
        "app.marketing_copilot.mentor.CaseMentorService", "app.marketing_copilot.mentor.context_packet",
        "app.marketing_copilot.mentor.explanation"},
}


def boundary_imports(source, boundary):
    imports = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and boundary in (node.module or ""):
            imports.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if boundary in alias.name)
    return imports


def assert_project_copilot_imports(root, path):
    relative = path.relative_to(root).as_posix()
    source = path.read_text(encoding="utf-8")
    assert boundary_imports(source, "marketing_copilot") == PROJECT_COPILOT_IMPORTS[relative], path
    assert "orchestration_runtime" not in source or relative == "app/services/project_history_service.py", path
