"""HTTP application adapter: identity/context acquisition, execution and projection."""
import asyncio
from dataclasses import replace
import logging
import time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.models import User
from app.module_execution.executors import ExecutorOutputError
from app.orchestration_runtime.errors import StartIdentityConflict
from app.product_context import OwnedSiteRequest, ConfirmedBusinessFact, ProductContextError
from app.product_context.projection import attach_acquisition, project_confirmation
from app.product_context.contracts import AcquisitionResult
from app.product_context.errors import SourceOutcome
from app.product_context.snapshot_store import OwnedSnapshotStore
from app.services.brand_profile_service import BrandProfileService
from app.module_registry import ToolCapability
from . import api_contracts as dto
from .api_errors import CopilotAPIError, ExecutionInvalid, ProviderUnavailable
from .application_contracts import CopilotRequest, ResultKind
from .http_context import current_entries, brand_entries
from .presentation import owned_result, module_presentation, calculation_presentation
from .provider_adapters import expected_provider_failure
from .run_reader import GraphRunReader
from .observability import stage_timing

log = logging.getLogger(__name__)


class CopilotAPIService:
    def __init__(self, *, sessions, copilot, acquisition, queue):
        self.sessions, self.copilot, self.acquisition, self.queue = sessions, copilot, acquisition, queue
        self.reader = GraphRunReader(sessions, copilot.graph_service)
        self.snapshots = OwnedSnapshotStore(sessions)

    async def close(self):
        await self.queue.close()

    async def _identity_context(self, actor):
        async with self.sessions() as session, session.begin():
            # Concurrent first requests share one internal identity.
            await session.execute(insert(User).values(telegram_id=actor).on_conflict_do_nothing(index_elements=[User.telegram_id]))
            user_id = await session.scalar(select(User.id).where(User.telegram_id == actor))
            profile = await BrandProfileService.get_by_user_id(session, user_id)
            return user_id, brand_entries(BrandProfileService.to_context(profile))

    async def execute(self, actor, payload):
        started = time.monotonic()
        with stage_timing("identity_context", request_key=payload.request_key, user_id=None):
            owner, brand = await self._identity_context(actor)
        request = CopilotRequest(actor_id=owner, request_id=payload.request_key, message=payload.message,
            current_request=current_entries(payload), brand_profile=brand,
            owned_site_url=payload.owned_site_url, available_tools=frozenset({ToolCapability.SITE_FETCH}))
        acquired = None
        try:
            async with asyncio.timeout(settings.GRAPH_TIMEOUT_SECONDS):
                if payload.owned_site_url is not None:
                    source = OwnedSiteRequest(owned_site_url=payload.owned_site_url)
                    if payload.confirmation is not None:
                        with stage_timing("owned_snapshot_load", request_key=payload.request_key, user_id=owner):
                            snapshot = await self.snapshots.load(owner, payload.request_key,
                                payload.confirmation.snapshot_id, payload.owned_site_url)
                            if snapshot is None:
                                raise CopilotAPIError(409, "confirmation_unavailable")
                        acquired = AcquisitionResult(source=source, outcome=SourceOutcome.ACQUIRED, snapshot=snapshot)
                    else:
                        with stage_timing("owned_acquisition", request_key=payload.request_key, user_id=owner):
                            acquired = await self.acquisition.acquire(source)
                        if acquired.snapshot is not None:
                            with stage_timing("owned_snapshot_save", request_key=payload.request_key, user_id=owner):
                                await self.snapshots.save(owner, payload.request_key, acquired.snapshot)
                    request = attach_acquisition(request, acquired)
                    if payload.confirmation is not None:
                        confirmation = payload.confirmation
                        try:
                            truth = project_confirmation(acquired.snapshot, ConfirmedBusinessFact(
                                snapshot_id=confirmation.snapshot_id, statement_ids=tuple(confirmation.statement_ids),
                                confirmed_by=f"user:{owner}", confirmation_reference=confirmation.reference))
                        except ProductContextError as exc:
                            raise CopilotAPIError(422, "invalid_confirmation") from exc
                        # Explicit current product_truth (even empty) outranks confirmation.
                        if "product_truth" not in payload.context.model_fields_set:
                            request = replace(request, current_request=(*request.current_request, truth))
                with stage_timing("core_execute", request_key=payload.request_key, user_id=owner):
                    result = await self.copilot.execute(request)
        except StartIdentityConflict as exc:
            raise CopilotAPIError(409, "request_conflict") from exc
        except ExecutorOutputError as exc:
            raise ExecutionInvalid() from exc
        except Exception as exc:
            if not expected_provider_failure(exc):
                raise
            raise ProviderUnavailable() from exc
        owned = owned_result(acquired, candidates=result.kind is ResultKind.NEEDS_INPUT) if acquired else None
        if result.kind is ResultKind.CONVERSATION:
            response = dto.ConversationResponse(owned_site=owned)
        elif result.kind is ResultKind.DIRECT_RESULT:
            response = dto.DirectResponse(calculation=calculation_presentation(result.direct_result), owned_site=owned)
        elif result.kind is ResultKind.MODULE_RESULT:
            response = dto.ModuleResponse(result=module_presentation(result.module_result), owned_site=owned)
        elif result.kind is ResultKind.WORKFLOW_STARTED:
            rid = result.workflow.run_id
            response = dto.StartedResponse(run_id=rid, status_url=f"/copilot/runs/{rid}", owned_site=owned)
        else:
            clarification = result.clarification
            if clarification.code == "provider_unavailable":
                raise ProviderUnavailable()
            response = dto.NeedsInputResponse(code=clarification.code,
                alternatives=[list(group) for group in clarification.alternatives],
                actions=["Supply the missing business context or review the source observations."], owned_site=owned)
        log.info("Copilot request user_id=%s request_key=%s kind=%s run_id=%s duration_ms=%s",
                 owner, payload.request_key, response.kind, getattr(response, "run_id", None),
                 int((time.monotonic() - started) * 1000))
        return response
