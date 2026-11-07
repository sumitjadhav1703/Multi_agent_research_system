"""One in-process queue consumer. This is not FastAPI BackgroundTasks.

The consumer thread leases a row, heartbeats on a second thread, runs the
graph, and writes the result. If the process dies first, the lease expires
and startup recovery queues the row again. A provider call that was in flight
can run again.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, Protocol

from sqlalchemy.orm import Session

from backend.app.jobs.executor import ExecutionResult
from backend.app.jobs.lease import heartbeat, lease_next, recover_expired_leases
from backend.app.jobs.persist import finalize_job
from backend.app.jobs.retention import retention_due, run_retention_pass
from backend.app.jobs.timeutil import utc_now
from backend.app.observability import emit, start_span

_consumer_guard = threading.Lock()
_running_consumer: QueueConsumer | None = None


class JobExecutor(Protocol):
    def execute(self, session_factory: Callable[[], Session], job_id: str) -> ExecutionResult: ...


def process_one(
    *,
    session_factory: Callable[[], Session],
    executor: JobExecutor,
    worker_id: str,
    lease_seconds: int,
    heartbeat_seconds: int,
) -> str | None:
    session = session_factory()
    try:
        job_id = lease_next(session, worker_id=worker_id, now=utc_now(), lease_seconds=lease_seconds)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    if job_id is None:
        return None

    with start_span("job.execute", job_id=job_id) as span:
        result = _execute_leased(session_factory, executor, worker_id, lease_seconds, heartbeat_seconds, job_id)
        span.set(
            status=result.status,
            provider_work_started=bool(result.provider_work_started),
            **{"error.code": result.error_code or "none"},
        )
    return job_id


def _execute_leased(
    session_factory: Callable[[], Session],
    executor: JobExecutor,
    worker_id: str,
    lease_seconds: int,
    heartbeat_seconds: int,
    job_id: str,
) -> ExecutionResult:
    stop = threading.Event()

    def _beat() -> None:
        while not stop.wait(max(heartbeat_seconds, 0.05)):
            beat = session_factory()
            try:
                owned = heartbeat(
                    beat,
                    job_id=job_id,
                    worker_id=worker_id,
                    now=utc_now(),
                    lease_seconds=lease_seconds,
                )
                beat.commit()
                if not owned:
                    return
            except Exception:
                beat.rollback()
                emit("job.heartbeat_failed", {"error.class": "database_error"}, level=logging.ERROR)
            finally:
                beat.close()

    beater = threading.Thread(target=_beat, name=f"heartbeat-{job_id[:8]}", daemon=True)
    beater.start()
    try:
        result = executor.execute(session_factory, job_id)
    except Exception:
        emit("job.execution_failed", {"error.class": "worker_exception"}, level=logging.ERROR)
        result = ExecutionResult(
            status="failed",
            provider_work_started=False,
            error_code="worker_exception",
            error_detail="worker_exception",
        )
    finally:
        stop.set()
        beater.join(timeout=1)
    finalize_job(session_factory, job_id, result, worker_id=worker_id)
    return result


class QueueConsumer:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        executor: JobExecutor,
        worker_id: str,
        lease_seconds: int = 60,
        heartbeat_seconds: int = 15,
        poll_seconds: float = 0.5,
        retention_enabled: bool = True,
        retention_days: int = 2,
        retention_interval_seconds: int = 3600,
        retention_batch_size: int = 100,
    ) -> None:
        self.session_factory = session_factory
        self.executor = executor
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.poll_seconds = poll_seconds
        self.retention_enabled = retention_enabled
        self.retention_days = retention_days
        self.retention_interval_seconds = retention_interval_seconds
        self.retention_batch_size = retention_batch_size
        self._last_retention_at: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        global _running_consumer
        with _consumer_guard:
            if self._thread and self._thread.is_alive():
                return
            active = _running_consumer
            if active is not None and active is not self and active._thread is not None and active._thread.is_alive():
                raise RuntimeError("A queue consumer is already running in this process.")
            self._stop.clear()
            thread = threading.Thread(target=self._loop, name="researchmind-queue", daemon=True)
            thread.start()
            self._thread = thread
            _running_consumer = self

    def stop(self) -> None:
        global _running_consumer
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        with _consumer_guard:
            if _running_consumer is self and (thread is None or not thread.is_alive()):
                _running_consumer = None

    def recover(self) -> list[str]:
        session = self.session_factory()
        try:
            recovered = recover_expired_leases(session)
            session.commit()
            return recovered
        except Exception:
            session.rollback()
            emit("job.lease_recovery_failed", {"error.class": "database_error"}, level=logging.ERROR)
            return []
        finally:
            session.close()

    def maybe_purge_retention(self, *, force: bool = False) -> None:
        """Delete rows older than retention_days when the interval elapses."""
        if not self.retention_enabled:
            return
        now = utc_now()
        if not force and not retention_due(
            last_run_at=self._last_retention_at,
            interval_seconds=self.retention_interval_seconds,
            now=now,
        ):
            return
        session = self.session_factory()
        try:
            run_retention_pass(
                session,
                retention_days=self.retention_days,
                now=now,
                batch_size=self.retention_batch_size,
            )
            session.commit()
            self._last_retention_at = now
        except Exception:
            session.rollback()
            emit("retention.failed", {"error.class": "database_error"}, level=logging.ERROR)
        finally:
            session.close()

    def _loop(self) -> None:
        self.recover()
        self.maybe_purge_retention(force=True)
        while not self._stop.is_set():
            worked = False
            try:
                self.maybe_purge_retention()
                worked = (
                    process_one(
                        session_factory=self.session_factory,
                        executor=self.executor,
                        worker_id=self.worker_id,
                        lease_seconds=self.lease_seconds,
                        heartbeat_seconds=self.heartbeat_seconds,
                    )
                    is not None
                )
            except Exception:
                emit("job.queue_iteration_failed", {"error.class": "database_error"}, level=logging.ERROR)
            if not worked:
                self._stop.wait(self.poll_seconds)


def consumer_enabled(app_state: Any, configured: bool) -> bool:
    override = getattr(app_state, "consumer_enabled", None)
    if override is not None:
        return bool(override)
    return configured
