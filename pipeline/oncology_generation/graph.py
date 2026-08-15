from __future__ import annotations

from pathlib import Path

from .nodes import build_timeline, draft_checkpoints, draft_task, load_case, persist_state, select_anchor, validate_node


def build_generation_graph(data_root: Path, client, allowed_tools: set[str]):
    from langgraph.graph import END, START, StateGraph
    from .schemas import GenerationState

    graph = StateGraph(GenerationState)
    graph.add_node("load_case", lambda state: load_case(data_root, state["case_id"]))
    graph.add_node("build_timeline", build_timeline)
    graph.add_node("select_anchor", lambda state: select_anchor(state, client))
    graph.add_node("draft_task", lambda state: draft_task(state, client))
    graph.add_node("draft_checkpoints", lambda state: draft_checkpoints(state, client))
    graph.add_node("validate", lambda state: validate_node(state, allowed_tools))
    graph.add_node("persist", lambda state: (persist_state(state, data_root / "generated" / state["case_id"]) or {}))
    graph.add_edge(START, "load_case")
    graph.add_edge("load_case", "build_timeline")
    graph.add_edge("build_timeline", "select_anchor")
    graph.add_edge("select_anchor", "draft_task")
    graph.add_edge("draft_task", "draft_checkpoints")
    graph.add_edge("draft_checkpoints", "validate")
    graph.add_edge("validate", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


def run_generation(case_id: str, data_root: Path, client, allowed_tools: set[str]):
    graph = build_generation_graph(data_root, client, allowed_tools)
    return graph.invoke({"case_id": case_id})
