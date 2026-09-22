"""Dedicated production entrypoint for Tickety OPS Tower scheduled jobs."""

import os
import signal
import threading
import time
from math import ceil
from pathlib import Path

from . import settings as settings_module
from .database import init_db
from .database import SessionLocal
from . import ticket_vectors
from .rag.embedding_worker import (
    embedding_worker_running,
    start_embedding_worker,
    stop_embedding_worker,
)
from .sync_worker import process_role, start_sync_worker, stop_sync_worker


_HEARTBEAT_PATH_ENV = "WORKER_HEARTBEAT_PATH"
_HEARTBEAT_MAX_AGE_ENV = "WORKER_HEALTHCHECK_MAX_AGE_SECONDS"
_RAG_HEARTBEAT_PATH_ENV = "WORKER_RAG_HEARTBEAT_PATH"
_RAG_HEALTH_REQUIRED_PATH_ENV = "WORKER_RAG_HEALTH_REQUIRED_PATH"
_DEFAULT_HEARTBEAT_PATH = "/tmp/tickety-worker-heartbeat"
_DEFAULT_RAG_HEARTBEAT_PATH = "/tmp/tickety-rag-embedding-heartbeat"
_DEFAULT_RAG_HEALTH_REQUIRED_PATH = "/tmp/tickety-rag-embedding-required"


def worker_heartbeat_path() -> Path:
    """Return the Pod-local worker health marker path."""
    return Path(os.getenv(_HEARTBEAT_PATH_ENV, _DEFAULT_HEARTBEAT_PATH))


def rag_embedding_heartbeat_path() -> Path:
    """Return the Pod-local marker for bounded RAG worker progress."""
    return Path(os.getenv(_RAG_HEARTBEAT_PATH_ENV, _DEFAULT_RAG_HEARTBEAT_PATH))


def rag_embedding_health_required_path() -> Path:
    """Return the parent worker's effective RAG-health contract marker."""
    return Path(
        os.getenv(_RAG_HEALTH_REQUIRED_PATH_ENV, _DEFAULT_RAG_HEALTH_REQUIRED_PATH)
    )


def worker_heartbeat_max_age_seconds() -> int:
    """Bound the interval after which incomplete scheduled work is unhealthy."""
    try:
        configured = int(os.getenv(_HEARTBEAT_MAX_AGE_ENV, "120"))
    except ValueError:
        configured = 120
    return max(30, min(configured, 600))


def write_worker_heartbeat() -> None:
    """Atomically record a completed scheduler cycle on the writable tmpfs."""
    path = worker_heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Several APScheduler executors can complete concurrently. Keep each
    # replace candidate distinct so one callback cannot remove another's
    # temporary marker before it is published.
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with temporary.open("w", encoding="ascii") as marker:
            marker.write(f"{time.time():.6f}\n")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_rag_embedding_heartbeat() -> None:
    """Atomically record a bounded embedding-worker progress checkpoint."""
    path = rag_embedding_heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with temporary.open("w", encoding="ascii") as marker:
            marker.write(f"{time.time():.6f}\n")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def configured_rag_embedding_heartbeat_max_age_seconds() -> int:
    """Bound a real provider call without hiding a blocked loop forever."""
    from .rag.config import worker_poll_seconds

    try:
        # A healthy empty queue waits up to the configured poll interval. A
        # nonempty queue may legally spend the provider's bounded timeout on a
        # single isolation leaf. Add a small filesystem/scheduling allowance.
        bounded_work_seconds = max(
            worker_poll_seconds(), ticket_vectors._embedding_timeout()
        )
    except ValueError:
        return worker_heartbeat_max_age_seconds()
    return max(
        worker_heartbeat_max_age_seconds(),
        min(600, int(ceil(bounded_work_seconds)) + 5),
    )


def write_rag_embedding_health_requirement(max_age_seconds: int) -> None:
    """Publish the parent worker's hydrated RAG liveness contract.

    Probe commands run in new Python processes and must not infer this from
    unhydrated environment variables or by opening the application database.
    """
    if not 30 <= max_age_seconds <= 600:
        raise ValueError("RAG heartbeat max age must be between 30 and 600")
    path = rag_embedding_health_required_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with temporary.open("w", encoding="ascii") as marker:
            marker.write(f"{max_age_seconds}\n")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def clear_worker_health_markers() -> None:
    """Do not let a prior local process grant a new worker startup grace."""
    for path in (
        worker_heartbeat_path(),
        rag_embedding_heartbeat_path(),
        rag_embedding_health_required_path(),
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _rag_embedding_health_requirement() -> tuple[bool, int | None]:
    path = rag_embedding_health_required_path()
    if not path.exists():
        return False, None
    try:
        value = int(path.read_text(encoding="ascii"))
    except (OSError, ValueError):
        return True, None
    return True, value if 30 <= value <= 600 else None


def _marker_is_recent(path: Path, max_age_seconds: int) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return 0 <= age <= max_age_seconds


def worker_healthcheck() -> bool:
    """Return whether a worker has recently completed scheduled work.

    This intentionally does not test the container PID: Kubernetes already
    knows whether that PID exists.  The marker is only refreshed after a
    scheduled callback returns, so a wedged scheduler/job executor eventually
    fails the probe and is restarted for durable lease recovery.
    """
    if not _marker_is_recent(
        worker_heartbeat_path(), worker_heartbeat_max_age_seconds()
    ):
        return False
    rag_required, rag_max_age_seconds = _rag_embedding_health_requirement()
    return not rag_required or (
        rag_max_age_seconds is not None
        and _marker_is_recent(rag_embedding_heartbeat_path(), rag_max_age_seconds)
    )


def _exit_after_heartbeat_stall(
    stopped: threading.Event,
    *,
    embedding_worker_required: bool = False,
    poll_interval_seconds: float = 5.0,
) -> None:
    """Exit a worker whose scheduler has stopped making durable progress.

    Kubernetes turns a failed liveness probe into a restart, but Docker Compose
    records an ``unhealthy`` status without restarting a still-running PID.
    Keeping this watchdog in-process gives both runtimes the same recovery
    behavior. It starts only after the initial readiness marker is published
    and stops before normal shutdown can make the marker stale.
    """
    while not stopped.wait(timeout=poll_interval_seconds):
        if embedding_worker_required and not embedding_worker_running():
            print("[worker] embedding worker stopped; exiting for durable recovery")
            os._exit(1)
        if not worker_healthcheck():
            print("[worker] heartbeat stalled; exiting for durable recovery")
            os._exit(1)


def _arm_heartbeat_watchdog(
    stopped: threading.Event, *, embedding_worker_required: bool = False
) -> None:
    watchdog = threading.Thread(
        target=_exit_after_heartbeat_stall,
        args=(stopped,),
        kwargs={"embedding_worker_required": embedding_worker_required},
        name="worker-heartbeat-watchdog",
        daemon=True,
    )
    watchdog.start()


def shutdown_deadline_seconds() -> int:
    """Return a bounded in-process shutdown budget.

    Kubernetes supplies extra termination-grace headroom after this deadline.
    The cap prevents a mistaken setting from turning SIGTERM into an
    indefinitely blocking deploy or node drain.
    """
    try:
        configured = int(os.getenv("WORKER_SHUTDOWN_DEADLINE_SECONDS", "20"))
    except ValueError:
        configured = 20
    return max(5, min(configured, 30))


def _force_exit_after_shutdown_deadline(deadline_seconds: int) -> None:
    """Guarantee SIGTERM completes even if APScheduler leaves an executor stuck.

    APScheduler delegates jobs to the stdlib's non-daemon ThreadPoolExecutor.
    ``shutdown(wait=False)`` closes admission but cannot kill a blocked job,
    which would otherwise keep this Python process alive after ``run``
    returns. This watchdog is armed only for an actual SIGTERM, never for a
    normal in-process stop or settings reload.
    """
    time.sleep(deadline_seconds)
    print("[worker] shutdown deadline reached; forcing exit for durable recovery")
    os._exit(0)


def _arm_sigterm_shutdown_watchdog(deadline_seconds: int) -> None:
    watchdog = threading.Thread(
        target=_force_exit_after_shutdown_deadline,
        args=(deadline_seconds,),
        name="worker-shutdown-deadline",
        daemon=True,
    )
    watchdog.start()


def run() -> int:
    role = process_role()
    if role not in {"worker", "all"}:
        print(
            "[worker] scheduler disabled for process role "
            f"{role!r}; set TICKETY_PROCESS_ROLE=worker"
        )
        return 2

    # Clear every inherited health marker before database initialization. A
    # container restart can retain /tmp or an emptyDir, so stale completion
    # evidence must not make a new process look healthy while startup blocks.
    clear_worker_health_markers()
    init_db()
    settings_module.load_settings_into_env()
    cleanup_db = SessionLocal()
    try:
        ticket_vectors.purge_private_comment_documents(cleanup_db)
    finally:
        cleanup_db.close()
    stopped = threading.Event()
    shutdown_started_at: float | None = None
    sigterm_watchdog_armed = False

    def request_shutdown(_signum, _frame):
        nonlocal shutdown_started_at, sigterm_watchdog_armed
        if stopped.is_set():
            return
        shutdown_started_at = time.monotonic()
        if _signum == signal.SIGTERM and not sigterm_watchdog_armed:
            _arm_sigterm_shutdown_watchdog(shutdown_deadline_seconds())
            sigterm_watchdog_armed = True
        stopped.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    scheduler_started = False
    embedding_worker_started = False
    try:
        # Pass the signal-owned predicate into both startup paths. A SIGTERM
        # between the initial check and an APScheduler/RAG thread creation
        # cannot be erased by their normal event-reset startup behavior.
        scheduler_started = start_sync_worker(
            admission_allowed=lambda: not stopped.is_set(),
            on_job_completion=write_worker_heartbeat,
        )
        if not scheduler_started:
            if stopped.is_set():
                return 0
            print("[worker] scheduler did not start")
            return 1
        if stopped.is_set():
            return 0

        embedding_worker_started = start_embedding_worker(
            admission_allowed=lambda: not stopped.is_set(),
            on_progress=write_rag_embedding_heartbeat,
        )
        if stopped.is_set():
            return 0
        if embedding_worker_started:
            rag_max_age_seconds = configured_rag_embedding_heartbeat_max_age_seconds()
            write_rag_embedding_health_requirement(rag_max_age_seconds)
            # The thread is live (the watchdog verifies that directly), while
            # its first provider call can legally consume the bounded deadline.
            # This marker supplies that startup grace until its first real
            # claim/provider/commit progress renewal arrives.
            write_rag_embedding_heartbeat()
            print("[rag-v2-worker] ready")

        # The initial marker makes readiness available once the scheduler and
        # optional embedding worker have both initialized. Later markers only
        # come from completed scheduler callbacks.
        write_worker_heartbeat()
        _arm_heartbeat_watchdog(
            stopped, embedding_worker_required=embedding_worker_started
        )
        print("[worker] ready")
        stopped.wait()
    finally:
        if scheduler_started or embedding_worker_started:
            deadline = shutdown_deadline_seconds()
            started_at = shutdown_started_at or time.monotonic()
            print(f"[worker] shutting down deadline_seconds={deadline}")
            # Close both admission gates before waiting. APScheduler's
            # ``shutdown(wait=True)`` has no timeout and can otherwise hold a Pod
            # forever behind a blocked provider/database job. Existing durable
            # sync and embedding leases are intentionally recovered by the next
            # worker rather than being force-cleared by a terminating process.
            stop_embedding_worker(wait=False)
            stop_sync_worker(wait=False)
            remaining = max(0.0, deadline - (time.monotonic() - started_at))
            embedding_stopped = stop_embedding_worker(
                wait=True,
                timeout_seconds=remaining,
            )
            if not embedding_stopped:
                print("[worker] embedding shutdown deadline reached; lease recovery deferred")
    return 0


if __name__ == "__main__":
    if "--healthcheck" in os.sys.argv[1:]:
        raise SystemExit(0 if worker_healthcheck() else 1)
    raise SystemExit(run())
