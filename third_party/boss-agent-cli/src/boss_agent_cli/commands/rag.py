from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import click

from boss_agent_cli.display import boss_command_for_ctx, handle_error_output, handle_output, render_simple_list
from boss_agent_cli.rag.chroma_health import check_chroma_runtime
from boss_agent_cli.rag.company_excel import (
    DEFAULT_COMPANY_SHEET,
    RagExcelDependencyError,
    chunks_from_company_row,
    load_company_rows_from_xlsx,
)
from boss_agent_cli.rag.models import RagChunk
from boss_agent_cli.rag.outreach_playbook import load_outreach_playbook_chunks
from boss_agent_cli.rag.progress import RagProgressStore
from boss_agent_cli.rag.resume_memory import ResumeRagImportError, chunks_from_resume, load_resume_for_rag
from boss_agent_cli.rag.store import ChromaRagStore, RagDependencyError

CHROMA_UNAVAILABLE_CODE = "RAG_CHROMA_UNAVAILABLE"
CHROMA_UNAVAILABLE_MESSAGE = "ChromaDB runtime smoke test failed; RAG chunks were staged for retry."


@click.group("rag")
def rag_group() -> None:
    """RAG context store for resumes, jobs, companies, and conversations."""


@rag_group.command("doctor")
@click.option("--collection", default="career_rag", help="ChromaDB collection name")
@click.option("--chroma-url", envvar="BOSS_RAG_CHROMA_URL", default=None, help="ChromaDB server URL")
@click.pass_context
def doctor_cmd(ctx: click.Context, collection: str, chroma_url: str | None) -> None:
    """Check local RAG dependencies and storage state."""
    data_dir = ctx.obj["data_dir"]
    checks: dict[str, Any] = {
        "chromadb": False,
        "openpyxl": False,
        "collection": collection,
        "backend": "http" if chroma_url else "local",
        "chroma_url": chroma_url,
    }
    try:
        import chromadb  # noqa: F401

        checks["chromadb"] = True
    except ModuleNotFoundError:
        checks["chromadb_error"] = "not installed"
    try:
        import openpyxl  # noqa: F401

        checks["openpyxl"] = True
    except ModuleNotFoundError:
        checks["openpyxl_error"] = "not installed"

    checks["persist_dir"] = str(data_dir / "rag" / "chroma")
    if checks["chromadb"]:
        health = check_chroma_runtime(chroma_url=chroma_url)
        checks["chroma_runtime"] = _compact_health(health)
        if health.get("ok"):
            try:
                store = ChromaRagStore(data_dir, collection_name=collection, chroma_url=chroma_url)
                checks["persist_dir"] = str(store.persist_dir)
                checks["count"] = store.count()
            except RagDependencyError as exc:
                checks["error"] = str(exc)
            except Exception as exc:
                checks["error"] = str(exc)
        else:
            checks["error"] = CHROMA_UNAVAILABLE_MESSAGE

    progress = RagProgressStore(data_dir, "company_excel_import")
    checks["progress"] = progress.read()
    handle_output(
        ctx,
        "rag",
        checks,
        hints={"next_actions": [boss_command_for_ctx(ctx, "rag index-companies --input <xlsx>")]},
    )


@rag_group.command("index-outreach-playbook")
@click.option(
    "--input",
    "input_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Outreach playbook JSON file",
)
@click.option("--collection", default="career_rag", help="ChromaDB collection name")
@click.option("--chroma-url", envvar="BOSS_RAG_CHROMA_URL", default=None, help="ChromaDB server URL")
@click.pass_context
def index_outreach_playbook_cmd(
    ctx: click.Context,
    input_path: str,
    collection: str,
    chroma_url: str | None,
) -> None:
    """Index the CareerReach outreach playbook into ChromaDB."""
    data_dir = ctx.obj["data_dir"]
    source_path = Path(input_path).expanduser().resolve()
    retry_command = boss_command_for_ctx(ctx, f'rag index-outreach-playbook --input "{source_path}"')
    try:
        chunks = load_outreach_playbook_chunks(source_path)
    except Exception as exc:
        handle_error_output(
            ctx,
            "rag",
            code="RAG_IMPORT_FAILED",
            message=str(exc),
            recoverable=True,
            recovery_action="Check outreach playbook JSON path and structure, then retry.",
        )
        return

    staging_path = _stage_chunks(data_dir, chunks, filename="outreach_playbook_chunks.json")
    health = check_chroma_runtime(chroma_url=chroma_url)
    if not health.get("ok"):
        handle_error_output(
            ctx,
            "rag",
            code=CHROMA_UNAVAILABLE_CODE,
            message=CHROMA_UNAVAILABLE_MESSAGE,
            recoverable=True,
            recovery_action=f"Fix ChromaDB runtime, then retry: {retry_command}",
            details={
                "staging_path": str(staging_path),
                "staged_chunks": len(chunks),
                "chroma_runtime": _compact_health(health),
            },
        )
        return

    try:
        store = ChromaRagStore(data_dir, collection_name=collection, chroma_url=chroma_url)
        indexed_chunks = store.upsert_chunks(chunks)
        collection_count = store.count()
    except RagDependencyError as exc:
        handle_error_output(
            ctx,
            "rag",
            code="RAG_DEPENDENCY_MISSING",
            message=str(exc),
            recoverable=True,
            recovery_action="pip install 'boss-agent-cli[rag]'",
        )
        return
    except Exception as exc:
        handle_error_output(
            ctx,
            "rag",
            code="RAG_IMPORT_FAILED",
            message=str(exc),
            recoverable=True,
            recovery_action=f"Staged chunks are preserved; retry: {retry_command}",
            details={"staging_path": str(staging_path)},
        )
        return

    handle_output(
        ctx,
        "rag",
        {
            "status": "completed",
            "source_path": str(source_path),
            "staging_path": str(staging_path),
            "indexed_chunks": indexed_chunks,
            "collection_count": collection_count,
            "collection": collection,
            "backend": "http" if chroma_url else "local",
            "chroma_url": chroma_url,
        },
        hints={"next_actions": [boss_command_for_ctx(ctx, 'rag search "CareerReach 六条话术" --doc-type message_template')]},
    )


@rag_group.command("index-resume")
@click.option("--name", "resume_name", default=None, help="Stored resume name under data/resumes")
@click.option(
    "--input",
    "input_path",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Resume JSON file; supports the native ResumeFile envelope",
)
@click.option("--collection", default="career_rag", help="ChromaDB collection name")
@click.option("--chroma-url", envvar="BOSS_RAG_CHROMA_URL", default=None, help="ChromaDB server URL")
@click.option("--reset-resume/--keep-existing", default=True, help="Delete old chunks for the same resume before indexing")
@click.pass_context
def index_resume_cmd(
    ctx: click.Context,
    resume_name: str | None,
    input_path: str | None,
    collection: str,
    chroma_url: str | None,
    reset_resume: bool,
) -> None:
    """Index a structured local resume into ChromaDB as doc_type=resume chunks."""
    data_dir = ctx.obj["data_dir"]
    source_path = Path(input_path).expanduser().resolve() if input_path else None
    retry_bits = ["rag index-resume"]
    if resume_name:
        retry_bits.extend(["--name", resume_name])
    if source_path:
        retry_bits.extend(["--input", f'"{source_path}"'])
    retry_command = boss_command_for_ctx(ctx, " ".join(retry_bits))
    try:
        resume = load_resume_for_rag(data_dir, resume_name=resume_name, input_path=source_path)
        chunks = chunks_from_resume(resume, source=str(source_path) if source_path else "resume_store")
    except ResumeRagImportError as exc:
        handle_error_output(
            ctx,
            "rag",
            code="RAG_IMPORT_FAILED",
            message=str(exc),
            recoverable=True,
            recovery_action="Check the resume name or JSON path, then retry.",
        )
        return
    except Exception as exc:
        handle_error_output(
            ctx,
            "rag",
            code="RAG_IMPORT_FAILED",
            message=str(exc),
            recoverable=True,
            recovery_action="Check resume JSON structure, then retry.",
        )
        return

    staging_path = _stage_chunks(data_dir, chunks, filename=f"resume_{_safe_filename(resume.name or 'resume')}_chunks.json")
    health = check_chroma_runtime(chroma_url=chroma_url)
    if not health.get("ok"):
        handle_error_output(
            ctx,
            "rag",
            code=CHROMA_UNAVAILABLE_CODE,
            message=CHROMA_UNAVAILABLE_MESSAGE,
            recoverable=True,
            recovery_action=f"Fix ChromaDB runtime, then retry: {retry_command}",
            details={
                "staging_path": str(staging_path),
                "staged_chunks": len(chunks),
                "resume_name": resume.name,
                "chroma_runtime": _compact_health(health),
            },
        )
        return

    try:
        store = ChromaRagStore(data_dir, collection_name=collection, chroma_url=chroma_url)
        if reset_resume:
            store.delete_where({"$and": [{"doc_type": "resume"}, {"resume_name": resume.name}]})
        indexed_chunks = store.upsert_chunks(chunks)
        collection_count = store.count()
    except RagDependencyError as exc:
        handle_error_output(
            ctx,
            "rag",
            code="RAG_DEPENDENCY_MISSING",
            message=str(exc),
            recoverable=True,
            recovery_action="pip install 'boss-agent-cli[rag]'",
        )
        return
    except Exception as exc:
        handle_error_output(
            ctx,
            "rag",
            code="RAG_IMPORT_FAILED",
            message=str(exc),
            recoverable=True,
            recovery_action=f"Staged chunks are preserved; retry: {retry_command}",
            details={"staging_path": str(staging_path)},
        )
        return

    handle_output(
        ctx,
        "rag",
        {
            "status": "completed",
            "resume_name": resume.name,
            "resume_title": resume.title,
            "source_path": str(source_path) if source_path else str(data_dir / "resumes" / f"{resume.name}.json"),
            "staging_path": str(staging_path),
            "indexed_chunks": indexed_chunks,
            "collection_count": collection_count,
            "collection": collection,
            "backend": "http" if chroma_url else "local",
            "chroma_url": chroma_url,
        },
        hints={"next_actions": [boss_command_for_ctx(ctx, 'rag search "AI customer service Agent Dify" --doc-type resume')]},
    )


@rag_group.command("index-companies")
@click.option(
    "--input",
    "input_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Opportunity Excel file",
)
@click.option("--sheet", "sheet_name", default=DEFAULT_COMPANY_SHEET, help="Sheet name to import")
@click.option("--collection", default="career_rag", help="ChromaDB collection name")
@click.option("--chroma-url", envvar="BOSS_RAG_CHROMA_URL", default=None, help="ChromaDB server URL")
@click.option("--limit", default=None, type=int, help="Maximum company rows to import")
@click.option("--reset", is_flag=True, default=False, help="Reset collection before indexing")
@click.pass_context
def index_companies_cmd(
    ctx: click.Context,
    input_path: str,
    sheet_name: str,
    collection: str,
    chroma_url: str | None,
    limit: int | None,
    reset: bool,
) -> None:
    """Index company/job context from an opportunity Excel workbook into ChromaDB."""
    data_dir = ctx.obj["data_dir"]
    source_path = Path(input_path).expanduser().resolve()
    progress = RagProgressStore(data_dir, "company_excel_import")
    payload = progress.start(
        source_path=str(source_path),
        sheet=sheet_name,
        collection=collection,
        chroma_url=chroma_url,
        backend="http" if chroma_url else "local",
        limit=limit,
        reset=reset,
    )

    try:
        rows = load_company_rows_from_xlsx(source_path, sheet_name=sheet_name, limit=limit)
    except RagExcelDependencyError as exc:
        _fail_progress(progress, payload, str(exc))
        handle_error_output(
            ctx,
            "rag",
            code="RAG_DEPENDENCY_MISSING",
            message=str(exc),
            recoverable=True,
            recovery_action="pip install 'boss-agent-cli[rag]'",
        )
        return
    except Exception as exc:
        _fail_progress(progress, payload, str(exc))
        handle_error_output(
            ctx,
            "rag",
            code="RAG_IMPORT_FAILED",
            message=str(exc),
            recoverable=True,
            recovery_action="Check Excel path, sheet name, and dependencies, then retry.",
        )
        return

    payload["total_rows"] = len(rows)
    if rows and rows[0].get("_source_sheet"):
        payload["resolved_sheet"] = rows[0]["_source_sheet"]
    progress.write(payload)

    staged_chunks: list[RagChunk] = []
    failed_rows: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows, start=1):
        try:
            resolved_sheet = str(row.get("_source_sheet") or sheet_name)
            chunks = chunks_from_company_row(row, source_path=source_path, sheet_name=resolved_sheet)
            staged_chunks.extend(chunks)
        except Exception as exc:
            failed_rows.append({"row_index": row_index, "source_row": row.get("_source_row"), "error": str(exc)})
        payload.update(
            {
                "processed_rows": row_index,
                "staged_chunks": len(staged_chunks),
                "failed_rows": failed_rows,
                "status": "staging",
            }
        )
        progress.write(payload)

    staging_path = _stage_chunks(data_dir, staged_chunks)
    retry_index_command = boss_command_for_ctx(ctx, f'rag index-companies --input "{source_path}" --reset')
    payload.update(
        {
            "status": "staged",
            "processed_rows": len(rows),
            "staged_chunks": len(staged_chunks),
            "failed_rows": failed_rows,
            "staging_path": str(staging_path),
            "progress_path": str(progress.path),
        }
    )
    progress.write(payload)

    health = check_chroma_runtime(chroma_url=chroma_url)
    payload["chroma_runtime"] = _compact_health(health)
    if not health.get("ok"):
        payload.update(
            {
                "status": "blocked_chromadb_unavailable",
                "last_error": CHROMA_UNAVAILABLE_MESSAGE,
                "indexed_chunks": 0,
            }
        )
        progress.write(payload)
        handle_error_output(
            ctx,
            "rag",
            code=CHROMA_UNAVAILABLE_CODE,
            message=CHROMA_UNAVAILABLE_MESSAGE,
            recoverable=True,
            recovery_action=f"Fix ChromaDB runtime, then retry: {retry_index_command}",
            details={
                "progress_path": str(progress.path),
                "staging_path": str(staging_path),
                "staged_chunks": len(staged_chunks),
                "chroma_runtime": _compact_health(health),
            },
        )
        return

    try:
        store = ChromaRagStore(data_dir, collection_name=collection, chroma_url=chroma_url)
        if reset:
            store.reset_collection()
        indexed_chunks = store.upsert_chunks(staged_chunks)
        collection_count = store.count()
    except RagDependencyError as exc:
        _fail_progress(progress, payload, str(exc))
        handle_error_output(
            ctx,
            "rag",
            code="RAG_DEPENDENCY_MISSING",
            message=str(exc),
            recoverable=True,
            recovery_action="pip install 'boss-agent-cli[rag]'",
        )
        return
    except Exception as exc:
        payload.update({"status": "failed_after_staging", "last_error": str(exc)})
        progress.write(payload)
        handle_error_output(
            ctx,
            "rag",
            code="RAG_IMPORT_FAILED",
            message=str(exc),
            recoverable=True,
            recovery_action=f"Staged chunks are preserved; retry: {retry_index_command}",
            details={"progress_path": str(progress.path), "staging_path": str(staging_path)},
        )
        return

    payload.update(
        {
            "status": "completed" if not failed_rows else "completed_with_errors",
            "processed_rows": len(rows),
            "indexed_chunks": indexed_chunks,
            "failed_rows": failed_rows,
            "collection_count": collection_count,
            "progress_path": str(progress.path),
            "persist_dir": str(store.persist_dir),
            "backend": store.backend,
            "chroma_url": chroma_url,
        }
    )
    payload = progress.write(payload)
    handle_output(
        ctx,
        "rag",
        payload,
        hints={"next_actions": [boss_command_for_ctx(ctx, 'rag search "AI 客服 产品经理"')]},
    )


@rag_group.command("search")
@click.argument("query")
@click.option("--top-k", default=5, type=int, help="Number of chunks to return")
@click.option(
	"--doc-type",
	default=None,
	type=click.Choice(["company", "job", "message_template", "resume"]),
	help="Filter by document type",
)
@click.option("--company", default=None, help="Filter by exact company name")
@click.option("--collection", default="career_rag", help="ChromaDB collection name")
@click.option("--chroma-url", envvar="BOSS_RAG_CHROMA_URL", default=None, help="ChromaDB server URL")
@click.pass_context
def search_cmd(
    ctx: click.Context,
    query: str,
    top_k: int,
    doc_type: str | None,
    company: str | None,
    collection: str,
    chroma_url: str | None,
) -> None:
    """Search the local RAG context store."""
    health = check_chroma_runtime(chroma_url=chroma_url)
    if not health.get("ok"):
        _handle_chroma_unavailable(ctx, health)
        return
    try:
        store = ChromaRagStore(ctx.obj["data_dir"], collection_name=collection, chroma_url=chroma_url)
        results = store.search(query, top_k=top_k, where=_where_filter(doc_type=doc_type, company=company))
    except RagDependencyError as exc:
        handle_error_output(
            ctx,
            "rag",
            code="RAG_DEPENDENCY_MISSING",
            message=str(exc),
            recoverable=True,
            recovery_action="pip install 'boss-agent-cli[rag]'",
        )
        return
    except Exception as exc:
        handle_error_output(
            ctx,
            "rag",
            code="RAG_SEARCH_FAILED",
            message=str(exc),
            recoverable=True,
            recovery_action="Check ChromaDB data directory, then retry.",
        )
        return
    items = [item.to_dict() for item in results]
    handle_output(
        ctx,
        "rag",
        {"query": query, "count": len(items), "items": items},
        render=lambda data: render_simple_list(
            [
                {
                    "company": item["metadata"].get("company", ""),
                    "doc_type": item["metadata"].get("doc_type", ""),
                    "score": round(item.get("score") or 0, 4),
                    "text": item.get("text", "")[:80],
                }
                for item in data["items"]
            ],
            "rag search",
            [
                ("company", "company", "green"),
                ("type", "doc_type", "cyan"),
                ("score", "score", "bold"),
                ("snippet", "text", "white"),
            ],
        ),
    )


@rag_group.command("stats")
@click.option("--collection", default="career_rag", help="ChromaDB collection name")
@click.option("--chroma-url", envvar="BOSS_RAG_CHROMA_URL", default=None, help="ChromaDB server URL")
@click.pass_context
def stats_cmd(ctx: click.Context, collection: str, chroma_url: str | None) -> None:
    """Show RAG store stats and last import progress."""
    progress = RagProgressStore(ctx.obj["data_dir"], "company_excel_import")
    health = check_chroma_runtime(chroma_url=chroma_url)
    if not health.get("ok"):
        handle_error_output(
            ctx,
            "rag",
            code=CHROMA_UNAVAILABLE_CODE,
            message=CHROMA_UNAVAILABLE_MESSAGE,
            recoverable=True,
            recovery_action="Fix ChromaDB runtime, then retry rag stats.",
            details={"progress": progress.read(), "chroma_runtime": _compact_health(health)},
        )
        return
    try:
        store = ChromaRagStore(ctx.obj["data_dir"], collection_name=collection, chroma_url=chroma_url)
        count = store.count()
        persist_dir = str(store.persist_dir)
    except RagDependencyError as exc:
        handle_error_output(
            ctx,
            "rag",
            code="RAG_DEPENDENCY_MISSING",
            message=str(exc),
            recoverable=True,
            recovery_action="pip install 'boss-agent-cli[rag]'",
        )
        return
    handle_output(
        ctx,
        "rag",
        {
            "collection": collection,
            "count": count,
            "persist_dir": persist_dir,
            "backend": "http" if chroma_url else "local",
            "chroma_url": chroma_url,
            "progress": progress.read(),
        },
    )


def _where_filter(*, doc_type: str | None, company: str | None) -> dict[str, Any] | None:
    clauses: list[dict[str, Any]] = []
    if doc_type:
        clauses.append({"doc_type": doc_type})
    if company:
        clauses.append({"company": company})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _stage_chunks(data_dir: Path, chunks: list[RagChunk], *, filename: str = "company_excel_chunks.json") -> Path:
    staging_dir = data_dir / "rag" / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_path = staging_dir / filename
    payload = {
        "created_at": time.time(),
        "count": len(chunks),
        "chunks": [chunk.to_dict() for chunk in chunks],
    }
    staging_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return staging_path


def _safe_filename(value: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value.strip())
    return clean or "resume"


def _handle_chroma_unavailable(ctx: click.Context, health: dict[str, Any]) -> None:
    handle_error_output(
        ctx,
        "rag",
        code=CHROMA_UNAVAILABLE_CODE,
        message=CHROMA_UNAVAILABLE_MESSAGE,
        recoverable=True,
        recovery_action="Fix ChromaDB runtime, then retry the RAG command.",
        details={"chroma_runtime": _compact_health(health)},
    )


def _compact_health(health: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in health.items():
        if key in {"stdout", "stderr"} and isinstance(value, str):
            compact[key] = value[-4000:]
        else:
            compact[key] = value
    return compact


def _fail_progress(progress: RagProgressStore, payload: dict[str, Any], error: str) -> None:
    payload["status"] = "failed"
    payload["last_error"] = error
    progress.write(payload)
