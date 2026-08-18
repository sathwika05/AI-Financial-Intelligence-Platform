"""
Run tagging for log records.

A benchmark drives the same graph, the same retrieval and the same nodes as a
user query, so their log lines are indistinguishable once interleaved in one
console — and they do interleave, because a benchmark runs as a background
task while the API keeps serving requests.

The tag is carried in a ContextVar rather than passed down through call
arguments or read out of `RunnableConfig`. Only the two entry points know
which kind of run this is, and everything below them — nodes, retrieval,
scoring, services — logs without ever receiving the LangGraph config. A
ContextVar reaches all of it and needs no change at the ~200 existing call
sites: a logging.Filter copies the value onto every record, and the format
string prints it.

ContextVars follow `await` and are copied into each task, so a background
benchmark and a concurrent request each keep their own tag.

    with benchmark_run(run_id):
        ...                       # every log line inside is tagged bench:1c9d4b7a
"""

from __future__ import annotations

import functools
import inspect
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import Any, Callable, Generator
from uuid import UUID, uuid4


# Printed for records emitted outside any run — startup, shutdown, uvicorn.
NO_RUN_TAG = "·········"

_run_tag: ContextVar[str] = ContextVar(
    "run_tag",
    default=NO_RUN_TAG,
)


def current_run_tag() -> str:
    """The tag applying to the caller's context."""
    return _run_tag.get()


@contextmanager
def _tagged(tag: str) -> Generator[str]:
    """
    Bind `tag` for the duration of the block.

    The token is reset on exit so a tag cannot leak into whatever the same
    task handles next — background tasks run in the request's context, so a
    bare `.set()` would keep tagging lines long after the run finished.
    """
    token = _run_tag.set(tag)

    try:
        yield tag
    finally:
        _run_tag.reset(token)


@contextmanager
def query_run(query_id: str | None = None) -> Generator[str]:
    """Tag a normal user-facing query: `query:a3f1c2`."""
    short = (
        query_id
        or uuid4().hex[:6]
    )

    with _tagged(f"query:{short}") as tag:
        yield tag


@contextmanager
def benchmark_run(run_id: UUID | str) -> Generator[str]:
    """
    Tag a benchmark run: `bench:1c9d4b7a`.

    Keyed by the run_id the dashboard shows, so a line in the console can be
    traced back to a row in benchmark_runs.
    """
    short = str(run_id).replace("-", "")[:8]

    with _tagged(f"bench:{short}") as tag:
        yield tag


class RunTagFilter(logging.Filter):
    """
    Stamp the current tag onto every record.

    Installed on the handler rather than on a logger: records from third-party
    loggers reach the same handler and would raise a formatting KeyError
    without the attribute.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_tag = _run_tag.get()
        return True


# ─────────────────────────── enter / exit spans ───────────────────────────


def _derive_prefix(module: str) -> str:
    """`backend.evaluation.benchmark_runner` -> `[BENCHMARK_RUNNER]`."""
    return f"[{module.rsplit('.', 1)[-1].upper()}]"


def _render(value: object) -> str:
    """
    Shorten a value to something safe to put on one log line.

    Whole DataFrames, ORM rows and context lists get passed around this
    pipeline; rendering one in full would bury the log.
    """
    if isinstance(value, (str, int, float, bool, UUID)) or value is None:
        text = str(value)
        return text if len(text) <= 60 else f"{text[:57]}..."

    # Enums (IntentType, BenchmarkStatus) read as VALUATION, not IntentType.
    if isinstance(value, Enum):
        return str(value.value)

    if isinstance(value, (list, tuple, set, dict)):
        return f"{type(value).__name__}({len(value)})"

    return type(value).__name__


def log_span(
    *fields: str,
    name: str | None = None,
    prefix: str | None = None,
    level: int = logging.INFO,
) -> Callable:
    """
    Log a start and an end line around a function.

    Written as a decorator because these functions have many return points
    and several `raise` paths — hand-written enter/exit calls would miss
    some, and the exit line would be lost entirely on an exception.

        @log_span("question_set", "top_k")
        async def run(self, *, config, run_id): ...

        [BENCHMARK_RUNNER] -> run question_set=valuation top_k=5
        [BENCHMARK_RUNNER] <- run ok 12480ms

    `fields` names the parameters worth showing. They are read by binding
    the call to the signature, so it makes no difference whether the caller
    passed them positionally or by keyword. A dotted field reaches into the
    argument — `"question.question_id"` logs the id rather than the object.
    Failures log at ERROR with the exception type, then re-raise unchanged.

    Wraps both sync and async functions; the async branch times the whole
    await rather than just the coroutine's creation.
    """

    def decorate(fn: Callable) -> Callable:
        signature = inspect.signature(fn)
        logger = logging.getLogger(fn.__module__)

        span_name = name or fn.__name__
        span_prefix = prefix or _derive_prefix(fn.__module__)

        def entry_line(args: tuple, kwargs: dict) -> str:
            if not fields:
                return ""

            try:
                bound = signature.bind_partial(*args, **kwargs)
            except TypeError:
                # Never let logging break a call the function itself
                # would have accepted.
                return ""

            shown = []

            for field in fields:
                root, _, path = field.partition(".")

                if root not in bound.arguments:
                    continue

                value = bound.arguments[root]

                for attribute in filter(None, path.split(".")):
                    value = getattr(value, attribute, None)

                shown.append(
                    f"{field.rsplit('.', 1)[-1]}={_render(value)}"
                )

            return (" " + " ".join(shown)) if shown else ""

        def log_enter(args: tuple, kwargs: dict) -> float:
            logger.log(
                level,
                "%s -> %s%s",
                span_prefix,
                span_name,
                entry_line(args, kwargs),
            )
            return time.perf_counter()

        def log_exit(started: float) -> None:
            logger.log(
                level,
                "%s <- %s ok %dms",
                span_prefix,
                span_name,
                (time.perf_counter() - started) * 1000,
            )

        def log_failure(started: float, exc: BaseException) -> None:
            logger.error(
                "%s <- %s FAILED %s: %s %dms",
                span_prefix,
                span_name,
                type(exc).__name__,
                exc,
                (time.perf_counter() - started) * 1000,
            )

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                started = log_enter(args, kwargs)

                try:
                    result = await fn(*args, **kwargs)
                except BaseException as exc:
                    log_failure(started, exc)
                    raise

                log_exit(started)
                return result

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            started = log_enter(args, kwargs)

            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:
                log_failure(started, exc)
                raise

            log_exit(started)
            return result

        return sync_wrapper

    return decorate
