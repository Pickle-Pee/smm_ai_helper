from types import SimpleNamespace

from fastapi.routing import APIRoute

from app.routers.agents import router as agents
from app.routers.chat_router import router as chat_router
from app.routers.copilot import router as copilot
from app.routers.images import router as images
from app.routers.projects import router as projects
from app.routers.tasks import router as tasks
from app.routers.workflows import router as workflows
from app.services.telegram_onboarding import missing_brand_steps
from app.telegram_admission import require_ready_profile


GENERATION = {
    ("POST", "/chat/message"), ("POST", "/copilot/execute"),
    ("POST", "/copilot/runs/{run_id}/mentor"), ("POST", "/copilot/runs/{run_id}/mentor/questions"),
    ("POST", "/projects/context/messages"), ("POST", "/workflows"),
    ("PATCH", "/workflows/{run_id}/context"), ("POST", "/workflows/{run_id}/continue"),
    ("POST", "/tasks/start"), ("POST", "/tasks/answer"), ("POST", "/agents/{agent_type}/run"),
    ("POST", "/images/generate"),
}


def test_only_generation_routes_are_gated():
    routers = (agents, chat_router, copilot, images, projects, tasks, workflows)
    guarded = {(method, route.path) for module in routers for route in module.routes
               if isinstance(route, APIRoute)
               and any(item.call is require_ready_profile for item in route.dependant.dependencies)
               for method in route.methods}
    assert guarded == GENERATION


def test_readiness_uses_only_meaningful_persisted_fields():
    assert missing_brand_steps(None) == ("product", "audience", "goal")
    profile = SimpleNamespace(product_description="Coffee", audience="  ", goals=[None, " "])
    assert missing_brand_steps(profile) == ("audience", "goal")
    profile.audience = "Neighbors"
    profile.goals = ["Visitors"]
    assert missing_brand_steps(profile) == ()
