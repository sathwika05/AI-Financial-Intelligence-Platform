"""
The graph keeps its state, so a run can be inspected after it finishes.

Without a checkpointer, LangGraph holds state only for the duration of one
invocation and discards it. Nothing fails -- the answer is returned and the
state is gone -- so "is this checkpointed?" cannot be answered by watching
it work.

These assert the two halves that make it real: the graph is compiled with a
checkpointer, and a thread's state is actually retrievable afterwards. The
first without the second passes on a graph that stores nothing, which is the
failure worth catching.
"""
import pytest


class TestTheGraphIsCheckpointed:
    def test_the_compiled_graph_has_a_checkpointer(self):
        from backend.graph.financial_graph import financial_graph

        assert financial_graph.checkpointer is not None, (
            "the graph compiled without a checkpointer, so no state survives "
            "an invocation"
        )

    @pytest.mark.asyncio
    async def test_a_thread_keeps_its_state_after_the_run(self):
        """
        The point of the checkpointer: state addressed by thread_id, still
        there once the graph has returned.
        """
        from langgraph.graph import END, START, StateGraph
        from typing_extensions import TypedDict

        from backend.checkpointing.saver import build_checkpointer

        class Tiny(TypedDict):
            value: str

        graph = StateGraph(Tiny)
        graph.add_node("step", lambda state: {"value": state["value"] + "!"})
        graph.add_edge(START, "step")
        graph.add_edge("step", END)

        compiled = graph.compile(checkpointer=build_checkpointer())
        config = {"configurable": {"thread_id": "test-thread"}}

        await compiled.ainvoke({"value": "hello"}, config=config)

        snapshot = compiled.get_state(config)

        assert snapshot.values["value"] == "hello!"

    @pytest.mark.asyncio
    async def test_threads_do_not_see_each_other(self):
        """
        Two questions asked at once must not share state. The thread_id is
        what separates them, and a checkpointer that ignored it would leak
        one caller's run into another's.
        """
        from langgraph.graph import END, START, StateGraph
        from typing_extensions import TypedDict

        from backend.checkpointing.saver import build_checkpointer

        class Tiny(TypedDict):
            value: str

        graph = StateGraph(Tiny)
        graph.add_node("step", lambda state: {"value": state["value"] + "!"})
        graph.add_edge(START, "step")
        graph.add_edge("step", END)

        compiled = graph.compile(checkpointer=build_checkpointer())

        await compiled.ainvoke({"value": "a"}, config={"configurable": {"thread_id": "one"}})
        await compiled.ainvoke({"value": "b"}, config={"configurable": {"thread_id": "two"}})

        one = compiled.get_state({"configurable": {"thread_id": "one"}})
        two = compiled.get_state({"configurable": {"thread_id": "two"}})

        assert one.values["value"] == "a!"
        assert two.values["value"] == "b!"


class TestEveryRunGetsItsOwnThread:
    def test_the_query_config_carries_a_thread_id(self):
        """
        A checkpointer with no thread_id raises at invoke time. Every caller
        of the graph has to supply one, so the helper that builds the config
        is where it belongs -- not at each call site, which is how one gets
        missed.
        """
        from backend.llm.usage_tracker import build_usage_config

        config, _ = build_usage_config(None)

        assert "configurable" in config
        assert config["configurable"].get("thread_id"), (
            "no thread_id on the config; the checkpointer cannot address "
            "this run"
        )

    def test_two_configs_get_different_threads(self):
        from backend.llm.usage_tracker import build_usage_config

        first, _ = build_usage_config(None)
        second, _ = build_usage_config(None)

        assert (
            first["configurable"]["thread_id"]
            != second["configurable"]["thread_id"]
        )


class TestAFinishedRunDoesNotHoldMemory:
    """
    MemorySaver keeps every thread it is given, for the life of the process.

    A benchmark runs a hundred questions through this graph, and each state
    carries retrieved_contexts, reranked_contexts, reranked_context_records
    and three result dicts. Kept, that is a hundred copies of the heaviest
    thing the pipeline produces, in a task that ECS killed for memory once
    already.

    The checkpoint is worth having during the run and worth nothing after
    it: the final state is already returned to the caller.
    """

    @pytest.mark.asyncio
    async def test_the_thread_is_released_when_the_run_ends(self):
        from langgraph.graph import END, START, StateGraph
        from typing_extensions import TypedDict

        from backend.checkpointing.saver import build_checkpointer
        from backend.graph.run import run_graph

        class Tiny(TypedDict):
            value: str

        graph = StateGraph(Tiny)
        graph.add_node("step", lambda state: {"value": state["value"] + "!"})
        graph.add_edge(START, "step")
        graph.add_edge("step", END)

        compiled = graph.compile(checkpointer=build_checkpointer())
        config = {"configurable": {"thread_id": "released-thread"}}

        result = await run_graph(compiled, {"value": "hello"}, config)

        assert result["value"] == "hello!", "the caller still gets the answer"

        snapshot = compiled.get_state(config)

        assert snapshot.values == {}, (
            "the thread's state outlived the run; a hundred of these is how "
            "the task runs out of memory"
        )
