"""Dedicated production entrypoint for Tickety OPS Tower scheduled jobs."""

import signal
import threading

from . import settings as settings_module
from .database import init_db
from .database import SessionLocal
from . import ticket_vectors
from .rag.embedding_worker import start_embedding_worker, stop_embedding_worker
from .sync_worker import process_role, start_sync_worker, stop_sync_worker


def run() -> int:
    init_db()
    settings_module.load_settings_into_env()
    cleanup_db = SessionLocal()
    try:
        ticket_vectors.purge_private_comment_documents(cleanup_db)
    finally:
        cleanup_db.close()
    role = process_role()
    if role not in {"worker", "all"}:
        print(
            "[worker] scheduler disabled for process role "
            f"{role!r}; set TICKETY_PROCESS_ROLE=worker"
        )
        return 2

    stopped = threading.Event()

    def request_shutdown(_signum, _frame):
        stopped.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    if not start_sync_worker():
        print("[worker] scheduler did not start")
        return 1

    embedding_worker_started = start_embedding_worker()
    if embedding_worker_started:
        print("[rag-v2-worker] ready")

    print("[worker] ready")
    try:
        stopped.wait()
    finally:
        print("[worker] shutting down")
        stop_embedding_worker(wait=True)
        stop_sync_worker(wait=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
