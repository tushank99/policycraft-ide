"""LangGraph supervisor graph.

            ┌────────────── supervisor ◀──────────────┐
            │      │        │         │         │     │
         triage remediation approval apply_fixes reporting
            └──────┴────────┴─────────┴─────────┴─────┘
                         (every worker reports back)
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents import nodes


def build_graph(checkpointer=None):
    g = StateGraph(nodes.TriageState)
    g.add_node("supervisor", nodes.supervisor)
    g.add_node("triage", nodes.triage)
    g.add_node("remediation", nodes.remediation)
    g.add_node("approval", nodes.approval)
    g.add_node("apply_fixes", nodes.apply_fixes)
    g.add_node("reporting", nodes.reporting)

    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", nodes.route, {
        "triage": "triage",
        "remediation": "remediation",
        "approval": "approval",
        "apply_fixes": "apply_fixes",
        "reporting": "reporting",
        "end": END,
    })
    for worker in ("triage", "remediation", "approval", "apply_fixes", "reporting"):
        g.add_edge(worker, "supervisor")
    return g.compile(checkpointer=checkpointer)
