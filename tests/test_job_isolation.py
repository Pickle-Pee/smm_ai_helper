from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[1]
SERVICE = ROOT / "app" / "services" / "job_persistence_service.py"


def parsed_service():
    return ast.parse(SERVICE.read_text(encoding="utf-8"))


def test_job_service_has_no_autonomous_transaction_calls():
    prohibited = {"commit", "rollback", "refresh", "expire", "expire_all"}
    calls = {
        node.func.attr
        for node in ast.walk(parsed_service())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert calls.isdisjoint(prohibited)


def test_job_service_imports_only_persistence_dependencies():
    imported_modules = set()
    for node in ast.walk(parsed_service()):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert imported_modules == {
        "__future__",
        "collections.abc",
        "copy",
        "datetime",
        "json",
        "math",
        "re",
        "sqlalchemy",
        "sqlalchemy.ext.asyncio",
        "sqlalchemy.orm.util",
        "typing",
        "app.models",
    }
    assert not any(
        token in module.lower()
        for module in imported_modules
        for token in (
            "redis",
            "openai",
            "telegram",
            "aiogram",
            "worker",
            "queue",
            "scheduler",
            "qc",
            "url",
            "image",
            "provider",
        )
    )


def test_current_runtime_paths_do_not_import_or_call_job_persistence():
    allowed = {
        ROOT / "app" / "models.py",
        SERVICE,
    }
    offenders = []
    for path in (ROOT / "app").rglob("*.py"):
        if path in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        if "JobPersistenceService" in source or "job_persistence_service" in source:
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_public_and_telegram_paths_have_no_job_contract_surface():
    roots = (ROOT / "app" / "routers", ROOT / "app" / "schemas", ROOT / "bot")
    offenders = []
    sources = [ROOT / "app" / "schemas.py", ROOT / "app" / "main.py"]
    for directory in roots:
        if not directory.is_dir():
            continue
        sources.extend(directory.rglob("*.py"))
    for path in sources:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        attributes = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        if {"Job", "JobStatus", "JobPersistenceService"} & (
            names | attributes
        ):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
