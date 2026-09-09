"""
Node-boundary tracing.

Owns the instrumentation applied at major graph boundaries. Three separate
mechanisms observe a run, and this module is responsible for only the first
two of them:

    console boundaries  — live visibility while a run is executing (here)
    LangSmith spans     — trace hierarchy, inspected afterwards
    node_timings        — persisted per-node latency for the dashboard (here)

LangSmith needs no work from this module. LangGraph already opens one run per
registered node, named after the string passed to `add_node`, and the
retrieval branches already carry `@traceable`. Wrapping nodes in another
`@traceable` here would emit a second span with the same name for the same
operation, so this module deliberately does not do that — it adds the console
boundary that was missing and leaves the trace hierarchy alone.

`timed_node` moved here from backend/graph/financial_graph.py. Its state
contract is unchanged: one `node_timings` entry per execution, `{"node",
"latency_ms"}`, which backend/evaluation/aggregation.py:build_node_latency
reads to build the dashboard's per-node panel.
"""

from __future__ import annotations

import functools
import inspect
import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Generator


logger = logging.getLogger(__name__)


# Kept distinct from the per-module prefixes ([HYBRID], [SCORING], ...) so a
# boundary line can be grepped out of a busy run: `grep '\[NODE\]'`.
NODE_PREFIX = "[NODE]"


@contextmanager
def node_boundary(name: str) -> Generator[Callable[[], float]]:
    """
    Log the start and end of one node execution.

        [NODE] sql -> start
        [NODE] sql <- ok 3842ms
        [NODE] sql <- failed 4210ms

    Yields a callable returning elapsed milliseconds, so a caller that needs
    the number for something else — `timed_node` persisting it — reads the
    same measurement that gets logged rather than taking a second one.

    A failing node logs at ERROR and the exception propagates untouched; this
    block never swallows, converts or delays it.
    """
    started = time.perf_counter()

    def elapsed_ms() -> float:
        return (time.perf_counter() - started) * 1000

    logger.info("%s %s -> start", NODE_PREFIX, name)

    try:
        yield elapsed_ms
    except BaseException:
        logger.error(
            "%s %s <- failed %.0fms",
            NODE_PREFIX,
            name,
            elapsed_ms(),
        )
        raise

    logger.info(
        "%s %s <- ok %.0fms",
        NODE_PREFIX,
        name,
        elapsed_ms(),
    )


def usage_snapshot(config) -> dict | None:
    """
    The tracker's counters right now, or None if there is no tracker.

    Found among the callbacks rather than passed in, because that is where
    build_usage_config already puts it and threading it through every node
    signature would change the graph's shape for a diagnostic.

    Duck-typed on the counter names rather than isinstance-checked, so
    tests can stand in a plain object and this module does not import the
    LLM layer.

    `callbacks` is a plain list when the config is built and an
    AsyncCallbackManager by the time LangGraph invokes a node, which is
    not iterable -- so both shapes are unwrapped here. Getting this wrong
    raises inside every node, which is exactly why the wrapper below is
    also defensive.
    """
    callbacks = (config or {}).get("callbacks")

    if callbacks is None:
        return None

    if not isinstance(callbacks, (list, tuple)):
        callbacks = (
            getattr(callbacks, "handlers", None)
            or getattr(callbacks, "inheritable_handlers", None)
            or []
        )

    for callback in callbacks:
        if all(
            hasattr(callback, attribute)
            for attribute in (
                "input_tokens", "output_tokens", "cost_usd", "call_count"
            )
        ):
            return {
                "tokens_in": callback.input_tokens,
                "tokens_out": callback.output_tokens,
                "cost": float(callback.cost_usd),
                "calls": callback.call_count,
            }

    return None


def usage_delta(before: dict | None, after: dict | None) -> dict | None:
    """
    What ran between two snapshots.

    Clamped at zero. The tracker only ever accumulates, so a negative
    delta means something is wrong upstream -- and a negative cost in a
    report is worse than a zero, because it silently reduces a total
    somebody is reading.

    A node that called nothing reports zeros rather than being dropped:
    scoring and output make no provider call, and "this stage is free" is
    a fact worth having in the breakdown.
    """
    if before is None or after is None:
        return None

    return {
        "tokens_in": max(0, after["tokens_in"] - before["tokens_in"]),
        "tokens_out": max(0, after["tokens_out"] - before["tokens_out"]),
        "cost_usd": round(max(0.0, after["cost"] - before["cost"]), 6),
        "calls": max(0, after["calls"] - before["calls"]),
    }


def timed_node(name: str, node: Callable) -> Callable:
    """
    Wrap a graph node so its wall-clock time is logged and recorded in state.

    Deliberately transparent: the node is awaited exactly as before and its
    return value is passed through untouched, with a single `node_timings`
    entry merged in. A node that raises is timed, logged and re-raised, so a
    failure is never hidden by the instrumentation.

    A node returning something other than a dict is passed straight through
    and contributes no timing entry — it has no state update to merge into.
    Every node in the financial graph returns a dict, so this affects
    nothing today; it is preserved as-is because changing it would add
    entries to `node_timings` and move the dashboard's numbers.

    Timings are appended, not assigned, because the reviewer can route back
    and a node can therefore run more than once per question.

    Sync and async nodes are both supported: the wrapper is async because
    LangGraph accepts async nodes either way, and a sync node's return value
    simply is not awaitable.
    """

    async def run(state, config):
        # Read either side of the node. Sound because graph nodes run one
        # at a time -- the parallel fan-out to SQL, vector and market
        # happens inside the retrieval node, not between nodes. If nodes
        # were ever run concurrently these deltas would interleave and
        # attribute to the wrong stage.
        usage_before = usage_snapshot(config)

        with node_boundary(name) as elapsed_ms:
            result = node(state, config)

            # Handles both node styles without inspecting the function up
            # front — a sync node returns its dict directly, an async one
            # returns a coroutine that must be awaited here rather than
            # leaking out un-awaited.
            if inspect.isawaitable(result):
                result = await result

            elapsed = elapsed_ms()

        timing = {
            "node": name,
            "latency_ms": round(elapsed, 3),
        }

        spent = usage_delta(usage_before, usage_snapshot(config))

        if spent is not None:
            timing.update(spent)

        if not isinstance(result, dict):
            # Nodes are expected to return state updates; anything else is
            # passed straight through rather than reshaped.
            return result

        return {
            **result,
            "node_timings": [timing],
        }

    return run


def node_span(name: str | None = None) -> Callable:
    """
    Log a console boundary around a function that is not a graph node.

    For the retrieval branches, which are real architectural boundaries but
    are called through `asyncio.gather` rather than registered with
    LangGraph. They already carry `@traceable`, so this adds the console
    line only and no second span.

        @traceable(name="branch_sql", ...)
        @node_span("sql")
        async def run_sql_retrieval_async(query, config): ...

    Unlike `timed_node` this touches no state and merges nothing into the
    return value.
    """

    def decorate(fn: Callable) -> Callable:
        label = name or fn.__name__

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with node_boundary(label):
                    return await fn(*args, **kwargs)

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with node_boundary(label):
                return fn(*args, **kwargs)

        return sync_wrapper

    return decorate
