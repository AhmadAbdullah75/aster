from sqlalchemy import select

from .db import transaction
from .models import Run, RunEvent


def emit(run_id: str, event_type: str, payload: dict):
    with transaction() as db:
        run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if not run:
            return
        run.seq += 1
        db.add(RunEvent(run_id=run_id, seq=run.seq, type=event_type, payload=payload))


def assert_active(run_id: str, worker_id: str | None = None):
    with transaction() as db:
        run = db.get(Run, run_id)
        if not run or run.cancel_requested or (worker_id and run.worker_id != worker_id):
            raise InterruptedError("Run canceled or lease lost")
