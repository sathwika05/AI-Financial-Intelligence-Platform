"""
Invoking a checkpointed graph without keeping the checkpoint.

MemorySaver holds every thread it is handed for the life of the process.
That is the right behaviour for a checkpointer and the wrong outcome here:
a benchmark sends a hundred questions through one graph, and each state
carries retrieved_contexts, reranked_contexts, reranked_context_records and
three result dicts. Kept, that is a hundred copies of the largest object
the pipeline builds, held by a task ECS has already killed once for memory.

The checkpoint earns its place during the run -- it is what lets the
reviewer loop back to retrieval or analysis without the graph losing where
it was. Afterwards it earns nothing: the final state has been returned to
the caller, and nothing reads the thread again.

So the thread is released when the run ends, and the graph keeps its
ability to resume mid-run.

Note for whoever swaps in a Postgres saver: this becomes a real decision
rather than a memory one. Persisted threads are how you inspect a run that
finished yesterday, and deleting them throws that away.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def run_graph(graph: Any, state: dict, config: dict) -> dict:
    """Invoke a checkpointed graph, then drop the thread it used."""
    try:
        return await graph.ainvoke(state, config=config)
    finally:
        await _release(graph, config)


async def _release(graph: Any, config: dict) -> None:
    """
    Delete this run's thread, and never fail the run for it.

    A checkpoint that cannot be deleted is a memory leak, not a broken
    answer. Raising here would turn a successful query into an error, so
    the failure is logged and the run stands.
    """
    thread_id = (config.get("configurable") or {}).get("thread_id")

    checkpointer = getattr(graph, "checkpointer", None)

    if not thread_id or checkpointer is None:
        return

    try:
        await checkpointer.adelete_thread(thread_id)
    except Exception:
        logger.warning(
            "[GRAPH] Could not release checkpoint thread %s", thread_id,
            exc_info=True,
        )
