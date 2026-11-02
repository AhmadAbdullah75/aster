import asyncio
import logging
import sys
from datetime import timedelta
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from sqlalchemy import select, update

from .agent import Context, build_graph, safe_error
from .config import settings
from .db import transaction
from .documents import ingest
from .events import assert_active, emit
from .graph_resources import resources
from .models import AuditEvent, Document, IngestionJob, Message, Proposal, Run, now, uid

logger = logging.getLogger("nexus.worker")


def recover():
    with transaction() as db:
        for proposal in db.scalars(
            select(Proposal)
            .where(Proposal.status == "pending", Proposal.expires_at < now())
            .with_for_update(skip_locked=True)
        ):
            proposal.status = "stale"
            run = db.get(Run, proposal.run_id)
            if run and run.status == "waiting":
                run.status, run.error = (
                    "failed",
                    "Approval expired. Send a new message to request a fresh proposal.",
                )
        for run in db.scalars(
            select(Run)
            .where(Run.status == "running", Run.lease_until < now())
            .with_for_update(skip_locked=True)
        ):
            run.status, run.error = (
                "failed",
                "Worker interrupted. Partial response retained; send a new message to retry. Approved writes are retained.",
            )
            for message in db.scalars(
                select(Message).where(Message.run_id == run.id, Message.role == "assistant")
            ):
                message.interrupted = True
            for proposal in db.scalars(
                select(Proposal).where(Proposal.run_id == run.id, Proposal.status == "pending")
            ):
                proposal.status = "stale"
            db.add(AuditEvent(user_id=run.user_id, action="run.recovered", resource_id=run.id))
        for job in db.scalars(
            select(IngestionJob)
            .where(IngestionJob.status == "processing", IngestionJob.lease_until < now())
            .with_for_update(skip_locked=True)
        ):
            job.status = "queued" if job.attempts < 3 else "failed"
            doc = db.get(Document, job.document_id)
            if doc:
                doc.status = job.status
                doc.error = (
                    "Worker stopped during ingestion; retry indexing."
                    if job.status == "failed"
                    else None
                )


def claim_run(worker_id: str):
    with transaction() as db:
        run = db.scalar(
            select(Run)
            .where(Run.status == "queued")
            .order_by(Run.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not run:
            return None
        if run.cancel_requested:
            run.status = "canceled"
            return None
        run.status, run.worker_id, run.lease_until = (
            "running",
            worker_id,
            now() + timedelta(seconds=30),
        )
        run.attempts += 1
        return run


async def heartbeat(run_id: str, worker_id: str, task):
    while not task.done():
        await asyncio.sleep(2)
        with transaction() as db:
            run = db.get(Run, run_id)
            if not run or run.cancel_requested or run.worker_id != worker_id:
                task.cancel()
                return
            run.lease_until = now() + timedelta(seconds=30)


async def process_run(run, worker_id, saver, store, model=None):
    graph = build_graph(saver, store)
    context = Context(
        user_id=run.user_id,
        thread_id=run.conversation_id,
        run_id=run.id,
        worker_id=worker_id,
        store=store,
        model=model,
    )
    config = {
        "configurable": {"thread_id": run.conversation_id},
        "recursion_limit": settings.max_tool_calls * 4 + 10,
    }
    value: Any
    if run.input.get("resume"):
        value = Command(resume={"decisions_persisted": True})
    else:
        value = {
            "messages": [HumanMessage(content=run.input["message"], id=f"human-{run.id}")],
            "mode": run.input.get("mode", "auto"),
            "document_ids": run.input.get("document_ids", []),
        }
    emit(run.id, "run.started", {"resumed": bool(run.input.get("resume"))})
    async with saver.conn.connection() as connection:
        await connection.execute("SELECT pg_advisory_lock(hashtext(%s))", (run.conversation_id,))
        try:
            assert_active(run.id, worker_id)
        except InterruptedError:
            # A claimed job may acquire the thread lock only after an API deletion has
            # completed. Never start graph checkpoint writes in that case.
            with transaction() as db:
                current = db.get(Run, run.id)
                if current and current.worker_id == worker_id:
                    current.status, current.lease_until = "canceled", None
            await connection.execute(
                "SELECT pg_advisory_unlock(hashtext(%s))", (run.conversation_id,)
            )
            return
        task = asyncio.create_task(graph.ainvoke(value, config, context=context))
        monitor = asyncio.create_task(heartbeat(run.id, worker_id, task))
        try:
            async with asyncio.timeout(settings.run_timeout_seconds):
                await task
            snapshot = await graph.aget_state(config)
            waiting = bool(snapshot.next)
            with transaction() as db:
                current = db.get(Run, run.id)
                if not current:
                    return
                current.status = "waiting" if waiting else "completed"
                current.lease_until = None
                if waiting:
                    proposals = [
                        p.id
                        for p in db.scalars(
                            select(Proposal).where(
                                Proposal.run_id == run.id, Proposal.status == "pending"
                            )
                        )
                    ]
                else:
                    proposals = []
            emit(
                run.id,
                "approval.required" if waiting else "run.completed",
                {"proposal_ids": proposals},
            )
        except (Exception, asyncio.CancelledError) as exc:
            canceled = isinstance(exc, (asyncio.CancelledError, InterruptedError))
            with transaction() as db:
                current = db.get(Run, run.id)
                if current:
                    current.status = "canceled" if canceled else "failed"
                    current.error = None if canceled else safe_error(exc)
                    current.lease_until = None
                    for message in db.scalars(
                        select(Message).where(Message.run_id == run.id, Message.role == "assistant")
                    ):
                        message.interrupted = True
            # Release the run lock before invalidating proposals: decisions acquire
            # their proposal lock first, so retaining both would invert lock order.
            with transaction() as db:
                db.execute(
                    update(Proposal)
                    .where(Proposal.run_id == run.id, Proposal.status == "pending")
                    .values(status="stale")
                )
            emit(
                run.id,
                "run.canceled" if canceled else "run.failed",
                {"error": None if canceled else safe_error(exc)},
            )
            logger.info(
                "Run %s terminal=%s exception=%s",
                run.id,
                "canceled" if canceled else "failed",
                type(exc).__name__,
            )
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
            await connection.execute(
                "SELECT pg_advisory_unlock(hashtext(%s))", (run.conversation_id,)
            )


async def ingestion_loop(worker_id):
    while True:
        with transaction() as db:
            job = db.scalar(
                select(IngestionJob)
                .where(IngestionJob.status == "queued")
                .order_by(IngestionJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job:
                job.status, job.worker_id = "processing", worker_id
                job.attempts += 1
                job.lease_until = now() + timedelta(seconds=240)
                doc = db.get(Document, job.document_id)
                doc.status = "processing"
                document_id = doc.id
            else:
                document_id = None
        if document_id:
            try:
                async with asyncio.timeout(210):
                    await ingest(document_id, worker_id)
            except Exception as exc:
                with transaction() as db:
                    doc = db.get(Document, document_id)
                    job = db.scalar(
                        select(IngestionJob).where(IngestionJob.document_id == document_id)
                    )
                    if doc and job and job.worker_id == worker_id:
                        doc.status, doc.error = "failed", safe_error(exc)
                        job.status = "failed"
        else:
            await asyncio.sleep(1)


async def main():
    worker_id = uid()
    async with resources(migrate=True) as (saver, store):
        ingestion = asyncio.create_task(ingestion_loop(worker_id))
        try:
            while True:
                recover()
                run = claim_run(worker_id)
                if run:
                    await process_run(run, worker_id, saver, store)
                else:
                    await asyncio.sleep(0.5)
        finally:
            ingestion.cancel()
            await asyncio.gather(ingestion, return_exceptions=True)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
