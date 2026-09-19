"""Owner-scoped, repeatable, read-only graph projections without execution/wakeups."""
from pydantic import ValidationError
from sqlalchemy import select, text

from app.models import MarketingRun, User
from app.orchestration_runtime.contracts import WORKFLOW_TYPE
from app.orchestration_runtime.errors import RuntimeContractError
from . import api_contracts as dto
from .api_errors import CopilotAPIError, ProviderUnavailable
from .presentation import module_presentation, coverage_presentation


class GraphRunReader:
    def __init__(self, sessions, graph_service):
        self.sessions, self.graph = sessions, graph_service

    async def get(self, telegram_id, run_id):
        async with self.sessions() as session, session.begin():
            # One committed snapshot prevents a worker's atomic completion from
            # being observed as mismatching Jobs/artifacts across SELECTs.
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            run = await session.scalar(select(MarketingRun).join(User).where(
                MarketingRun.run_id == run_id, MarketingRun.workflow_type == WORKFLOW_TYPE,
                User.telegram_id == telegram_id))
            if run is None:
                raise CopilotAPIError(404, "not_found")
            try:
                # Reuse exact persisted identity, dependency and full-claim gate
                # validation. These helpers only SELECT/evaluate; never lock/write.
                revision, plan = await self.graph._plan(session, run_id)
                jobs, accepted = await self.graph._graph_state(session, run_id, revision, plan)
                status = dto.RunStatus(run.status.upper())
                presentations = [module_presentation(accepted[n.node_id]) for n in plan.nodes if n.node_id in accepted]
                coverage = coverage_presentation(run.state_json, {n.node_id: n.module_id for n in plan.nodes})
                limits = list(dict.fromkeys([*(coverage.limitations if coverage else []),
                    *(v for p in presentations for v in p.limitations)]))[:64]
                failure = None
                if status is dto.RunStatus.BLOCKED:
                    # Only explicitly allowlisted public meanings cross this boundary.
                    failure = dto.PublicFailure(code="context_required", message="Additional context or an accessible source is required.",
                        actions=["Review the supplied context and sources, then submit a new request key."])
                elif status is dto.RunStatus.FAILED:
                    failure = dto.PublicFailure(code="result_unavailable", message="The request could not be completed.",
                        actions=["Contact support with the run ID or submit a new request key."])
                return dto.RunResponse(run_id=run_id, status=status,
                    strategy=next((p for p in presentations if isinstance(p, dto.Strategy)), None),
                    experiments=next((p for p in presentations if isinstance(p, dto.Experiments)), None),
                    details=[p for p in presentations if isinstance(p, dto.Findings)],
                    evidence_coverage=coverage, limitations=limits, failure=failure)
            except (RuntimeContractError, ValidationError) as exc:
                # Invalid persisted contracts must not expose partially trusted data.
                raise ProviderUnavailable() from exc
