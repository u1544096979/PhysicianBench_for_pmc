from __future__ import annotations

from pathlib import Path

from .nodes import build_timeline, load_case, materialize_cleaned_node, persist_state, select_target_group, validate_node


class _LinearGraph:
    """Keep the fixed pipeline runnable when an optional runtime is unavailable."""

    def __init__(self, nodes):
        self._nodes = nodes

    def invoke(self, state):
        current = dict(state)
        for node in self._nodes:
            current.update(node(current))
        return current


def build_generation_graph(data_root: Path, client, allowed_tools: set[str]):
    from .schemas import GenerationState

    nodes = [
        lambda state: load_case(data_root, state["case_id"]),
        build_timeline,
        lambda state: select_target_group(state, client),
        lambda state: materialize_cleaned_node(state, data_root),
        validate_node,
        lambda state: (persist_state(state, data_root / "generated" / state["case_id"]) or {}),
    ]
    try:
        from langgraph.graph import END, START, StateGraph
    except ModuleNotFoundError as exc:
        if exc.name != "langgraph":
            raise
        return _LinearGraph(nodes)

    graph = StateGraph(GenerationState)
    for name, node in zip(("load_case", "build_timeline", "select_target_group", "materialize_cleaned_case", "validate", "persist"), nodes):
        graph.add_node(name, node)
    graph.add_edge(START, "load_case")
    graph.add_edge("load_case", "build_timeline")
    graph.add_edge("build_timeline", "select_target_group")
    graph.add_edge("select_target_group", "materialize_cleaned_case")
    graph.add_edge("materialize_cleaned_case", "validate")
    graph.add_edge("validate", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


def run_generation(case_id: str, data_root: Path, client, allowed_tools: set[str]):
    graph = build_generation_graph(data_root, client, allowed_tools)
    return graph.invoke({"case_id": case_id})
