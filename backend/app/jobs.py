"""Background jobs: one at a time, in a thread, with progress stored in the database.

Handlers are registered with @handler("type") and receive a JobContext. A job
interrupted by a restart is marked 'interrupted' and can be resumed; handlers
skip work already stored for the same job.
"""
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from .db import session_scope
from .models import Job, now

HANDLERS = {}


def handler(name):
    def register(fn):
        HANDLERS[name] = fn
        return fn
    return register


class Cancelled(Exception):
    pass


class JobContext:
    def __init__(self, job_id, params, echo=None):
        self.job_id = job_id
        self.params = params
        self.echo = echo
        self._cancel = threading.Event()

    def progress(self, done=None, total=None, message=None):
        with session_scope() as s:
            job = s.get(Job, self.job_id)
            if done is not None:
                job.done = done
            if total is not None:
                job.total = total
            if message is not None:
                job.message = message
        if self.echo and message:
            self.echo(f"[{done or 0}/{total or '?'}] {message}" if total else message)

    def log(self, line):
        with session_scope() as s:
            job = s.get(Job, self.job_id)
            job.log = (job.log + line + "\n")[-20000:]
        if self.echo:
            self.echo(line)

    def cancelled(self):
        return self._cancel.is_set()

    def check(self):
        if self._cancel.is_set():
            raise Cancelled()


class JobRunner:
    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="job")
        self._contexts = {}
        self._lock = threading.Lock()

    def recover(self):
        """Jobs left running by a previous process are marked interrupted."""
        with session_scope() as s:
            for job in s.scalars(select(Job).where(Job.status.in_(("queued", "running")))).all():
                job.status = "interrupted"
                job.message = "Stopped when the app was closed. Resume to continue."

    def submit(self, type_, params=None, job_id=None):
        """Queue a job (or re-queue an interrupted one) and return its id."""
        if type_ not in HANDLERS:
            raise ValueError(f"Unknown job type {type_!r}")
        with session_scope() as s:
            if job_id is None:
                job = Job(type=type_, params=params or {})
                s.add(job)
                s.flush()
            else:
                job = s.get(Job, job_id)
                job.status, job.finished_at = "queued", None
            job_id, params = job.id, job.params
        ctx = JobContext(job_id, params)
        with self._lock:
            self._contexts[job_id] = ctx
        self._pool.submit(self._run, type_, ctx)
        return job_id

    def run_sync(self, type_, params=None, echo=print):
        """Run a job in the calling thread (CLI)."""
        with session_scope() as s:
            job = Job(type=type_, params=params or {})
            s.add(job)
            s.flush()
            job_id = job.id
        self._run(type_, JobContext(job_id, params or {}, echo=echo))
        return job_id

    def cancel(self, job_id):
        with self._lock:
            ctx = self._contexts.get(job_id)
        if ctx:
            ctx._cancel.set()
            return True
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job and job.status == "queued":
                job.status = "cancelled"
                return True
        return False

    def busy(self):
        with self._lock:
            return bool(self._contexts)

    def _run(self, type_, ctx):
        with session_scope() as s:
            job = s.get(Job, ctx.job_id)
            if job.status == "cancelled":
                return
            job.status, job.started_at, job.message = "running", job.started_at or now(), "Starting"
        status, message, summary = "done", "", None
        try:
            summary = HANDLERS[type_](ctx)
            message = (summary or {}).get("message", "Done")
        except Cancelled:
            status, message = "cancelled", "Cancelled"
        except Exception as exc:  # shown in the UI; the job must not take the runner down
            status, message = "failed", f"{type(exc).__name__}: {exc}"
            ctx.log(traceback.format_exc())
        finally:
            with session_scope() as s:
                job = s.get(Job, ctx.job_id)
                job.status, job.finished_at, job.message = status, now(), message
                if summary is not None:
                    job.summary = {**(job.summary or {}), **summary}
            with self._lock:
                self._contexts.pop(ctx.job_id, None)
            if ctx.echo and status != "done":
                ctx.echo(message)


runner = JobRunner()


def job_dict(job):
    return {
        "id": job.id, "type": job.type, "params": job.params, "status": job.status,
        "done": job.done, "total": job.total, "message": job.message,
        "summary": {k: v for k, v in (job.summary or {}).items() if k != "manifest"},
        "legacy_id": job.legacy_id, "created_at": job.created_at, "started_at": job.started_at,
        "finished_at": job.finished_at,
    }
