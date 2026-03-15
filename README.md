# kanoniv-langgraph

Cryptographic identity and delegation for LangGraph agents.

Every agent gets a `did:agent:` DID. Every node execution carries a delegation proof. Authority flows from human to graph to agent, narrowing at each step.

## Install

```bash
pip install kanoniv-langgraph
```

## Quick Start

```python
from kanoniv_agent_auth import AgentKeyPair
from kanoniv_langgraph import DelegatedGraph, delegated_node, DelegationState
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

# Root authority (human or system)
root = AgentKeyPair.generate()
graph = DelegatedGraph(root)

# Add agents with scoped permissions
researcher = graph.add_agent("researcher", scope=["search"], max_cost=5.0, expires_in_hours=24)
writer = graph.add_agent("writer", scope=["write"], max_cost=3.0)

print(f"Root:       {graph.root_did}")
print(f"Researcher: {researcher.did}")
print(f"Writer:     {writer.did}")


# Define state with delegation context
class MyState(DelegationState):
    query: str
    results: str
    report: str


# Gate nodes behind delegation verification
@delegated_node(graph, researcher, action="search")
def search_node(state: MyState) -> dict:
    return {"results": f"Found results for: {state['query']}"}

@delegated_node(graph, writer, action="write")
def write_node(state: MyState) -> dict:
    return {"report": f"Report on: {state['results']}"}


# Build the LangGraph workflow
workflow = StateGraph(MyState)
workflow.add_node("search", search_node)
workflow.add_node("write", write_node)
workflow.add_edge(START, "search")
workflow.add_edge("search", "write")
workflow.add_edge("write", END)

app = workflow.compile()
result = app.invoke({"query": "AI delegation patterns"})
# Every node execution is verified against the delegation chain
```

## Sub-Delegation

Agents can delegate to sub-agents with narrower scope:

```python
# Orchestrator delegates to a specialized searcher
searcher = graph.sub_delegate(
    researcher,
    "searcher",
    scope=["search"],
    max_cost=2.0,  # narrower than researcher's $5
)

# searcher can only execute "search" nodes, max $2 per call
# researcher can search at max $5
# writer can only write at max $3
```

## Revocation

```python
# Revoke an agent's delegation
graph.revoke(writer)

# All subsequent node executions by writer will return:
# {"delegation_error": "Agent 'writer' delegation has been revoked"}
```

## DelegationState

`DelegationState` is a `TypedDict` that carries delegation context through the graph state. Merge it into your state type:

```python
from kanoniv_langgraph import DelegationState

class MyState(DelegationState):
    # Your fields
    query: str
    results: str

# After a verified node executes, the state contains:
# {
#     "delegation_agent": "researcher",
#     "delegation_did": "did:agent:abc123...",
#     "delegation_root_did": "did:agent:root...",
#     "delegation_chain": ["did:agent:root...", "did:agent:abc123..."],
#     "delegation_depth": 1,
#     "delegation_error": None,
#     "delegation_log": [{"agent": "researcher", "action": "search", ...}],
#     "query": "...",
#     "results": "..."
# }
```

## Audit Trail

```python
# Get time-sorted audit log from all agents
for entry in graph.audit_log():
    print(f"{entry['timestamp']} {entry['agent']} ({entry['did'][:20]}...) {entry['action']}")
```

## How It Works

1. `DelegatedGraph(root_keypair)` creates a root authority
2. `graph.add_agent(name, scope, max_cost)` generates a keypair and delegation for each agent
3. `@delegated_node(graph, agent)` wraps node functions with verification
4. Before each node executes, the delegation chain is verified:
   - Is the delegation still valid (not expired, not revoked)?
   - Is the action in the agent's scope?
   - Is the cost within limits?
5. If verification fails, the node returns `{"delegation_error": "..."}` in the state
6. If verification passes, the node executes and delegation metadata is merged into state

The delegation chain is cryptographic (Ed25519 signatures). It cannot be forged, tampered with, or escalated. Caveats can only narrow, never widen.

## API

### DelegatedGraph

| Method | Description |
|--------|-------------|
| `add_agent(name, scope, max_cost, expires_in_hours, resource)` | Create an agent with delegation from root |
| `sub_delegate(from_agent, name, scope, max_cost)` | Create a sub-agent with narrower delegation |
| `get_agent(name)` | Look up agent by name |
| `revoke(agent)` | Revoke an agent's delegation |
| `is_revoked(agent)` | Check if delegation is revoked |
| `verify_node(agent, action, args)` | Verify delegation and return state updates |
| `audit_log()` | Get combined audit log from all agents |

### DelegatedAgent

| Property/Method | Description |
|----------------|-------------|
| `did` | The agent's `did:agent:` DID |
| `identity` | The agent's `AgentIdentity` |
| `keypair` | The agent's `AgentKeyPair` |
| `create_proof(action, args)` | Create an MCP proof for a tool call |
| `verify_action(action, args)` | Verify delegation allows this action |
| `history` | List of verified actions |

### delegated_node

| Parameter | Description |
|-----------|-------------|
| `graph` | The `DelegatedGraph` managing delegation chains |
| `agent` | The `DelegatedAgent` whose delegation to verify |
| `action` | Override the action name (defaults to function name) |

### DelegationState

| Field | Type | Description |
|-------|------|-------------|
| `delegation_agent` | `str` | Name of the agent executing the current node |
| `delegation_did` | `str` | DID of the executing agent |
| `delegation_root_did` | `str` | DID of the root authority |
| `delegation_chain` | `list[str]` | DIDs in the delegation path |
| `delegation_depth` | `int` | Chain depth (0 = root) |
| `delegation_error` | `str \| None` | Error message if node was denied |
| `delegation_log` | `list[dict]` | Append-only audit trail |

## Links

- [kanoniv-agent-auth](https://github.com/kanoniv/agent-auth) - The core identity and delegation library
- [LangGraph](https://langchain-ai.github.io/langgraph/) - Framework for building stateful, multi-agent applications
- [MCP Auth Proposal](https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/2404) - Adding agent delegation to the MCP spec

## License

MIT
