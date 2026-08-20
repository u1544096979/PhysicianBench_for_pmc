"""v2 流水线 LangGraph 编排."""
from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from . import nodes as N
from .schemas import GenerationState


def build_generation_graph() -> StateGraph:
    graph = StateGraph(GenerationState)

    graph.add_node("load_and_timeline", N.load_and_timeline)
    graph.add_node("label_recommend", N.label_recommend)
    graph.add_node("generate_task", N.generate_task)
    graph.add_node("validate_task", N.validate_task)
    graph.add_node("solve_task", N.solve_task)
    graph.add_node("evaluate_solution", N.evaluate_solution)
    graph.add_node("inject_noise", N.inject_noise)
    graph.add_node("generate_checkpoints", N.generate_checkpoints)
    graph.add_node("materialize", N.materialize)
    graph.add_node("persist_failure", N.persist_failure)

    graph.add_edge(START, "load_and_timeline")
    graph.add_edge("load_and_timeline", "label_recommend")
    graph.add_conditional_edges(
        "label_recommend",
        N.route_after_label,
        {
            "generate_task": "generate_task",
            "persist_failure": "persist_failure",
        },
    )
    graph.add_edge("generate_task", "validate_task")
    graph.add_conditional_edges(
        "validate_task",
        N.route_after_validate,
        {
            "solve_task": "solve_task",
            "generate_task": "generate_task",
            "persist_failure": "persist_failure",
        },
    )
    graph.add_edge("solve_task", "evaluate_solution")
    graph.add_conditional_edges(
        "evaluate_solution",
        N.route_after_evaluate,
        {
            "inject_noise": "inject_noise",      # valid 分支
            "generate_task": "generate_task",
            "persist_failure": "persist_failure",
        },
    )
    graph.add_edge("inject_noise", "generate_checkpoints")
    graph.add_edge("generate_checkpoints", "materialize")
    graph.add_edge("materialize", END)
    graph.add_edge("persist_failure", END)
    return graph


_compiled = None


def get_compiled_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_generation_graph().compile()
    return _compiled


def run_case(
    case_id: str,
    *,
    data_root: Path,
    output_root: Path,
    generated_root: Path,
    force_relabel: bool = False,
) -> GenerationState:
    from .schemas import new_state

    state = new_state(
        case_id=case_id,
        data_root=data_root,
        output_root=output_root,
        generated_root=generated_root,
        force_relabel=force_relabel,
    )
    app = get_compiled_graph()
    final = app.invoke(state, config={"recursion_limit": 50})
    return final
