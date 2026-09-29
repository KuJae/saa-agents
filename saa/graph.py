"""그래프 배선.

    macro_agent
        ↓
    asset_agents ←──────────┐
        ↓                   │
    challenger              │ 미해결 반박 있고 round < 3
        ↓                   │
    converged? ─────────────┘
        ↓ 수렴 또는 상한
    (halt_debate)
        ↓
    cov_estimator → optimizers → ips_gate
        ↓                            ↓ 통과 0건
    review_agents                 escalate (사람 개입)
        ↓
    risk_agent → combine → memo_writer
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from . import nodes
from .llm import DETERMINISTIC, VARIANCE, LLMClient
from .state import SAAState


def build(*, mode: str = "mock", cache_ns: str = "default",
          variance: bool = False, checkpointer=None):
    """그래프를 컴파일해 반환. LLM 클라이언트도 함께 돌려준다."""
    client = LLMClient(mode=mode, cache_ns=cache_ns,
                       params=dict(VARIANCE if variance else DETERMINISTIC))
    nodes.LLM = client

    g = StateGraph(SAAState)

    g.add_node("macro_agent", nodes.macro_agent)
    g.add_node("asset_agents", nodes.asset_agents)
    g.add_node("challenger", nodes.challenger)
    g.add_node("revise_agents", nodes.revise_agents)
    g.add_node("halt_debate", nodes.halt_debate)
    g.add_node("cov_estimator", nodes.cov_estimator)
    g.add_node("optimizers", nodes.optimizers)
    g.add_node("ips_gate", nodes.ips_gate)
    g.add_node("escalate", nodes.escalate)
    g.add_node("review_agents", nodes.review_agents)
    g.add_node("risk_agent", nodes.risk_agent)
    g.add_node("combine", nodes.combine)
    g.add_node("memo_writer", nodes.memo_writer)

    g.add_edge(START, "macro_agent")
    g.add_edge("macro_agent", "asset_agents")
    g.add_edge("asset_agents", "challenger")

    # ── 토론 루프 ──
    g.add_conditional_edges("challenger", nodes.route_debate,
                            {"revise_agents": "revise_agents",
                             "halt_debate": "halt_debate",
                             "cov_estimator": "cov_estimator"})
    g.add_edge("revise_agents", "challenger")
    g.add_edge("halt_debate", "cov_estimator")

    g.add_edge("cov_estimator", "optimizers")
    g.add_edge("optimizers", "ips_gate")

    # ── 사람 개입 분기 ──
    g.add_conditional_edges("ips_gate", nodes.route_ips,
                            {"escalate": "escalate",
                             "review_agents": "review_agents"})
    g.add_edge("escalate", END)

    g.add_edge("review_agents", "risk_agent")
    g.add_edge("risk_agent", "combine")
    g.add_edge("combine", "memo_writer")
    g.add_edge("memo_writer", END)

    return g.compile(checkpointer=checkpointer or MemorySaver()), client
