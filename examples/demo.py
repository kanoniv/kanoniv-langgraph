"""
kanoniv-langgraph demo: delegation chain with verification.

Run: python examples/demo.py

Shows:
1. Root delegates to orchestrator with [search, analyze, report]
2. Orchestrator sub-delegates to researcher with [search] only
3. search_node: VERIFIED (researcher has search in scope)
4. analyze_node: VERIFIED (orchestrator has analyze in scope)
5. deploy_node: DENIED (not in anyone's scope)
6. Sub-delegation enforcement and revocation
"""

from kanoniv_agent_auth import AgentKeyPair
from kanoniv_langgraph import DelegatedGraph, delegated_node, DelegationState


# -- Simulated graph state --------------------------------------------------

class WorkflowState(DelegationState):
    """Graph state that carries both workflow data and delegation context."""
    query: str
    results: str
    analysis: str
    report: str


# -- Setup -------------------------------------------------------------------

def main():
    print("=== kanoniv-langgraph Demo ===\n")

    # Root authority (human or orchestration platform)
    root = AgentKeyPair.generate()
    graph = DelegatedGraph(root)
    print(f"Root DID:         {graph.root_did}")

    # Orchestrator agent - broad scope
    orchestrator = graph.add_agent(
        "orchestrator",
        scope=["search", "analyze", "report"],
        expires_in_hours=24,
    )
    print(f"Orchestrator DID: {orchestrator.did}")

    # Researcher agent - sub-delegated from orchestrator, narrower scope
    researcher = graph.sub_delegate(
        orchestrator,
        "researcher",
        scope=["search"],
    )
    print(f"Researcher DID:   {researcher.did}")

    # -- Define nodes with delegation verification --------------------------

    @delegated_node(graph, researcher, action="search")
    def search_node(state: dict) -> dict:
        return {"results": f"Found 42 results for: {state.get('query', '???')}"}

    @delegated_node(graph, orchestrator, action="analyze")
    def analyze_node(state: dict) -> dict:
        return {"analysis": f"Analysis of: {state.get('results', 'nothing')}"}

    @delegated_node(graph, orchestrator, action="deploy")
    def deploy_node(state: dict) -> dict:
        return {"report": "Deployed to production"}

    # -- Execute nodes and show results -------------------------------------

    state = {"query": "LangGraph delegation patterns"}

    # [1] search_node - researcher has "search" in scope
    print("\n[1] search_node (researcher, action=search)...")
    result = search_node(state)
    if result.get("delegation_error"):
        print(f"    DENIED: {result['delegation_error']}")
    else:
        print(f"    VERIFIED: chain depth {result['delegation_depth']}, "
              f"path: {' -> '.join(result['delegation_chain'])}")
        print(f"    Output: {result.get('results')}")
    state.update(result)

    # [2] analyze_node - orchestrator has "analyze" in scope
    print("\n[2] analyze_node (orchestrator, action=analyze)...")
    result = analyze_node(state)
    if result.get("delegation_error"):
        print(f"    DENIED: {result['delegation_error']}")
    else:
        print(f"    VERIFIED: chain depth {result['delegation_depth']}, "
              f"path: {' -> '.join(result['delegation_chain'])}")
        print(f"    Output: {result.get('analysis')}")
    state.update(result)

    # [3] deploy_node - orchestrator does NOT have "deploy" in scope
    print("\n[3] deploy_node (orchestrator, action=deploy)...")
    result = deploy_node(state)
    if result.get("delegation_error"):
        print(f"    DENIED: {result['delegation_error']}")
    else:
        print(f"    VERIFIED (unexpected): {result}")
    state.update(result)

    # [4] Researcher tries to analyze (not in sub-delegated scope)
    print("\n[4] researcher tries analyze (not in scope)...")
    try:
        researcher.verify_action("analyze")
        print("    ERROR: should have been blocked")
    except ValueError as e:
        print(f"    DENIED: {e}")

    # [5] Revocation
    print("\n[5] Revoking researcher...")
    graph.revoke(researcher)
    print(f"    Researcher revoked: {graph.is_revoked(researcher)}")

    # [6] search_node after revocation
    print("\n[6] search_node after revocation...")
    result = search_node(state)
    if result.get("delegation_error"):
        print(f"    DENIED: {result['delegation_error']}")
    else:
        print(f"    ERROR: should have been denied")

    # [7] Audit log
    print(f"\n[7] Audit log: {len(graph.audit_log())} verified executions")
    for entry in graph.audit_log():
        print(f"    {entry['agent']} ({entry['did'][:24]}...) -> {entry['action']}")

    print("\nDone.")


if __name__ == "__main__":
    main()
