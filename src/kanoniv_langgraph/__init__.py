"""Cryptographic identity and delegation for LangGraph agents.

Add verifiable agent identity and attenuated delegation to any LangGraph workflow.
Every node execution carries a cryptographic proof of authority.

    pip install kanoniv-langgraph

Usage:

    from kanoniv_langgraph import DelegatedGraph, delegated_node, DelegationState
    from kanoniv_agent_auth import AgentKeyPair

    root = AgentKeyPair.generate()
    graph = DelegatedGraph(root)

    researcher = graph.add_agent("researcher", scope=["search", "analyze"], max_cost=5.0)
    writer = graph.add_agent("writer", scope=["write"], max_cost=3.0)

    # Every node execution by these agents carries a delegation proof
    # verifiable back to the root authority.
"""

from kanoniv_langgraph.core import (
    DelegatedGraph,
    DelegatedAgent,
    DelegationState,
    NodeResult,
    delegated_node,
)

__all__ = [
    "DelegatedGraph",
    "DelegatedAgent",
    "DelegationState",
    "NodeResult",
    "delegated_node",
]
