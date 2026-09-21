"""Strict bounded wire contracts for the intelligence executors (payload.v1)."""
from typing import Annotated, Literal
from pydantic import Field
from .schemas import OutputBase, OutputStatement, StrictOutput, Reference

ShortText = Annotated[str, Field(min_length=1, max_length=300)]

class MarketStatement(OutputStatement):
    output_name: Literal[
        'market_definition',
        'category_structure',
        'market_size_if_supported',
        'demand_drivers',
        'demand_barriers',
        'segments',
        'segment_attractiveness',
        'JTBD',
        'CEP',
        'alternatives',
        'audience_findings',
        'market_opportunities',
        'white_spaces',
        'research_gaps.',
    ]


class StrategyStatement(OutputStatement):
    output_name: Literal[
        'strategic_diagnosis',
        'main_growth_constraint',
        'strategic_priorities',
        'trade_offs',
        'resource_priorities',
        'strategic_bets',
        'roadmap',
        'risks',
        'decision_triggers.',
    ]
    items: list[ShortText] = Field(min_length=1, max_length=3)


class ExperimentStatement(OutputStatement):
    output_name: Literal[
        'hypothesis',
        'evidence_basis',
        'mechanism',
        'test_method',
        'control',
        'treatment',
        'population',
        'primary_metric',
        'guardrails',
        'MDE_logic',
        'sample_logic',
        'duration_logic',
        'stop_rule',
        'scale_rule',
        'decision_tree',
        'learning_record.',
    ]


class MarketOutput(OutputBase):
    outputs: list[MarketStatement] = Field(min_length=1, max_length=14)


class StrategyOutput(OutputBase):
    outputs: list[StrategyStatement] = Field(min_length=1, max_length=9)


class ExperimentDesign(StrictOutput):
    hypothesis: ShortText
    target_metric: ShortText
    intervention: ShortText
    expected_signal: ShortText
    failure_condition: ShortText
    minimum_required_inputs: list[ShortText] = Field(min_length=1, max_length=5)
    time_resource_constraints: list[ShortText] = Field(max_length=8)
    related_strategic_claim_ids: list[Reference] = Field(min_length=1, max_length=8)


class ExperimentsOutput(OutputBase):
    outputs: list[ExperimentStatement] = Field(min_length=1, max_length=16)
    experiments: list[ExperimentDesign] = Field(min_length=1, max_length=3)


class SuppliedMarketSource(StrictOutput):
    source_reference: Annotated[str, Field(min_length=1, max_length=2048)]
    source_class: Literal["EXTERNAL_PRIMARY", "EXTERNAL_SECONDARY"]
    excerpt: Annotated[str, Field(min_length=1, max_length=8000)]
