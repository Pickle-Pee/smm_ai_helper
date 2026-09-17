"""Strict versioned JSON codecs. No dynamic imports or Python object tags."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from app.marketing_orchestrator.contracts import AuthorizedContextFact, UpstreamFinding
from app.module_execution.contracts import ModuleExecutionResult
from app.module_registry import ModuleId
from .contracts import CompiledExecutionPlan
from .errors import RuntimeContractError

MAX_BYTES = 1_048_576
MAX_DEPTH = 24


def to_json(value, depth=0):
    if depth > MAX_DEPTH:
        raise RuntimeContractError("serialization depth exceeded")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise RuntimeContractError("naive timestamp")
        return value.astimezone(timezone.utc).isoformat()
    if is_dataclass(value):
        return {f.name: to_json(getattr(value, f.name), depth + 1) for f in fields(value)}
    if isinstance(value, Mapping):
        if any(type(k) is not str for k in value):
            raise RuntimeContractError("non-string JSON key")
        return {k: to_json(v, depth + 1) for k, v in value.items()}
    if type(value) in (tuple, list, frozenset):
        result = [to_json(v, depth + 1) for v in value]
        return sorted(result, key=canonical) if type(value) is frozenset else result
    if value is None or type(value) in (bool, int, str, float):
        if type(value) is int and not -(2**63) <= value < 2**63:
            raise RuntimeContractError("integer out of range")
        if type(value) is float and not math.isfinite(value):
            raise RuntimeContractError("non-finite JSON")
        if type(value) is str and ("\x00" in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value)):
            raise RuntimeContractError("invalid JSON Unicode")
        return value
    raise RuntimeContractError("unsupported JSON value")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def bounded(value):
    raw = to_json(value)
    if len(canonical(raw).encode("utf-8")) > MAX_BYTES:
        raise RuntimeContractError("serialization byte limit exceeded")
    return raw


def fingerprint(value):
    return hashlib.sha256(canonical(bounded(value)).encode("utf-8")).hexdigest()


def _decode(kind, value):
    origin, args = get_origin(kind), get_args(kind)
    if kind is Any:
        return value
    if origin in (Union, UnionType):
        for option in args:
            try:
                return _decode(option, value)
            except (ValueError, TypeError):
                pass
        raise RuntimeContractError("invalid union shape")
    if origin is Literal:
        if type(value) is not str or value not in args:
            raise RuntimeContractError("invalid literal")
        return value
    if origin in (tuple, frozenset):
        if type(value) is not list:
            raise RuntimeContractError("invalid sequence shape")
        result = tuple(_decode(args[0], v) for v in value)
        if origin is frozenset and len(set(result)) != len(result):
            raise RuntimeContractError("duplicate set member")
        return frozenset(result) if origin is frozenset else result
    if isinstance(kind, type) and issubclass(kind, Enum):
        if type(value) is not str:
            raise RuntimeContractError("invalid enum shape")
        return kind(value)
    if kind is datetime:
        if type(value) is not str:
            raise RuntimeContractError("invalid timestamp shape")
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise RuntimeContractError("naive timestamp")
        return result
    if is_dataclass(kind):
        names = {f.name for f in fields(kind) if f.init}
        if type(value) is not dict or set(value) != names:
            raise RuntimeContractError("unknown or missing persisted fields")
        hints = get_type_hints(kind)
        values = {}
        for name in names:
            # JSON payloads and fact values are already bounded/validated JSON.
            if (kind in (AuthorizedContextFact, UpstreamFinding) and name == "value") or (
                kind is ModuleExecutionResult and name == "payload"
            ):
                values[name] = value[name]
            else:
                values[name] = _decode(hints[name], value[name])
        return kind(**values)
    if type(value) is not kind:
        raise RuntimeContractError("invalid scalar shape")
    return value


def _restore(kind, raw):
    try:
        bounded(raw)
        result = _decode(kind, raw)
        if bounded(result) != raw:
            raise RuntimeContractError("non-canonical persisted shape")
        return result
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        raise RuntimeContractError("invalid persisted contract") from exc


def result_to_json(result: ModuleExecutionResult):
    if type(result) is not ModuleExecutionResult:
        raise RuntimeContractError("invalid execution result")
    raw = bounded(result)
    result_from_json(raw)
    return raw


def result_from_json(raw) -> ModuleExecutionResult:
    result = _restore(ModuleExecutionResult, raw)
    if (result.module_id not in {ModuleId.COMPETITOR_ANALYSIS, ModuleId.POSITIONING, ModuleId.CREATOR}
            or result.schema_version != result.module_id.value.lower() + ".payload.v1"):
        raise RuntimeContractError("unsupported execution result payload version")
    return result


def plan_to_json(plan: CompiledExecutionPlan):
    from .compiler import validate_compiled_plan
    validate_compiled_plan(plan)
    return bounded(plan)


def plan_from_json(raw) -> CompiledExecutionPlan:
    from .compiler import validate_compiled_plan
    plan = _restore(CompiledExecutionPlan, raw)
    validate_compiled_plan(plan)
    return plan
