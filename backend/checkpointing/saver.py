"""
Where the graph's state is kept between steps.

LangGraph runs a graph without a checkpointer perfectly well: state passes
from node to node and is discarded when the run ends. What that costs is
everything after the run -- there is no way to ask what the state was at the
reviewer, or to resume a run that stopped, because nothing was kept.

MemorySaver keeps it in this process's memory. That is honest about what it
is: it does not survive a restart, and two API tasks would each hold their
own. ECS replaced the API task four times in one afternoon, so on this
deployment a checkpoint's useful life is measured in minutes.

The reason to use it anyway is that it is the seam. Swapping in
AsyncPostgresSaver is a change to this function and nothing else -- every
caller already addresses state by thread_id, which is the part that has to
be right first and the part that is awkward to retrofit.

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    # and settings.DATABASE_URL, and a one-time .setup()

That needs langgraph-checkpoint-postgres, which is not installed. Adding it
changes uv.lock, which rebuilds the dependency layer, which means pushing
the whole image again rather than a small derived one -- on a connection
that needed a chunked uploader to manage 4.36 GB once.
"""
from langgraph.checkpoint.memory import MemorySaver


# One saver for the process. A checkpointer per graph would give each its
# own store, and a thread_id would then mean different things depending on
# which graph you asked -- which is worse than not having one.
_saver = MemorySaver()


def build_checkpointer() -> MemorySaver:
    """The checkpointer every graph in this process shares."""
    return _saver
