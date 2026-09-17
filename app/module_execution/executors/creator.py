"""A ready text post and creative rationales; never generates image references."""
from app.marketing_orchestrator.quality_gates.contracts import BlockingReason
from app.module_registry import ModuleId

from .common import BaseExecutor, blocked, facts_for, first_party_evidence, parent_claims, scoped_facts
from .schemas import CreatorOutput


class CreatorExecutor(BaseExecutor):
    module_id = ModuleId.CREATOR
    executor_key = "creator.v1"
    schema_version = "creator.payload.v1"
    output_type = CreatorOutput
    instruction = """Create a ready-to-use text marketing post in post.headline/body/cta from the
supplied product, audience and message. The outputs contain requested creative
choices and short rationales, not factual evidence made from the ad itself.
Use POSITIONING predecessor claims when supplied and cite material lineage.
Textual scripts, visual briefs and image prompts are only concepts, not produced
media. No new discounts, scarcity, testimonials, awards, numbers, social proof or
guarantees. Do not promise platform-specific current compliance without evidence."""
    limitation = "Text post and creative hypotheses only; no image/video generation, platform-current compliance or performance validation."

    async def execute(self, request):
        early = self.prepare(request)
        if early is not None:
            return early
        facts = scoped_facts(request)
        formats = facts_for(facts, "asset_format")
        # Explicit format prevents an image/video request being silently answered with text.
        if len(formats) != 1 or formats[0].value != "text_post":
            return blocked(request, self.schema_version, BlockingReason.MISSING_CAPABILITY,
                           "CREATOR v1 requires explicit asset_format=text_post; other assets are unsupported")
        missing = []
        if not (facts_for(facts, "product") or facts_for(facts, "product_or_offer")):
            missing.append("product_or_offer")
        parents = parent_claims(request)
        positioning = [c for u in request.upstream_results if u.module_id is ModuleId.POSITIONING
                       for c in u.result.normalized_result.claims if c.claim_id in parents]
        if not facts_for(facts, "target_or_target_hypothesis") and not any(c.declared_output_name == "target" for c in positioning):
            missing.append("target_or_target_hypothesis")
        if not (facts_for(facts, "message") or facts_for(facts, "product_truth")) and not any(
            c.declared_output_name in ("value_proposition", "positioning_statement", "message_hierarchy") for c in positioning
        ):
            missing.append("message/product_truth or POSITIONING message")
        if missing:
            return blocked(request, self.schema_version, BlockingReason.MISSING_BLOCKING_INPUT, ", ".join(missing))
        return await self.generate(request, first_party_evidence(request, facts))

    def validate_statement(self, statement, local, parents):
        if statement.kind == "OBSERVATION":
            raise ValueError("Creative choices must not be presented as factual observations")

    def build_result(self, request, output, evidence, parents):
        facts = scoped_facts(request)
        required_upstream_outputs = []
        if not facts_for(facts, "target_or_target_hypothesis"):
            required_upstream_outputs.append({"target"})
        if not (facts_for(facts, "message") or facts_for(facts, "product_truth")):
            required_upstream_outputs.append({"value_proposition", "positioning_statement", "message_hierarchy"})
        cited = {p for statement in output.outputs for p in statement.parent_claim_ids}
        positioning_ids = {c.claim_id for upstream in request.upstream_results if upstream.module_id is ModuleId.POSITIONING
                           for c in upstream.result.normalized_result.claims}
        for outputs in required_upstream_outputs:
            if not any(p in positioning_ids and p in parents and parents[p].declared_output_name in outputs for p in cited):
                raise ValueError("Missing lineage for required upstream positioning context")
        return super().build_result(request, output, evidence, parents)
