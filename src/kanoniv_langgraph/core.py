"""Core delegation primitives for LangGraph."""

import json
import functools
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, TypedDict

from kanoniv_agent_auth import (
    AgentKeyPair,
    AgentIdentity,
    Delegation,
    Invocation,
    McpProof,
    verify_invocation,
)


# ---------------------------------------------------------------------------
# State types
# ---------------------------------------------------------------------------

class DelegationState(TypedDict, total=False):
    """Delegation context carried through the LangGraph state.

    Merge this into your graph's state TypedDict so that delegation
    metadata flows between nodes automatically.

    Fields:
        delegation_agent: Name of the agent executing the current node.
        delegation_did: DID of the executing agent.
        delegation_root_did: DID of the root authority.
        delegation_chain: List of DIDs in the delegation path.
        delegation_depth: Chain depth (0 = root).
        delegation_error: Set when a node is denied execution.
        delegation_log: Append-only audit trail of verified node executions.
    """

    delegation_agent: str
    delegation_did: str
    delegation_root_did: str
    delegation_chain: list[str]
    delegation_depth: int
    delegation_error: str | None
    delegation_log: list[dict[str, Any]]


class NodeResult(TypedDict, total=False):
    """Convenience type for node return values that include delegation state."""

    delegation_agent: str
    delegation_did: str
    delegation_root_did: str
    delegation_chain: list[str]
    delegation_depth: int
    delegation_error: str | None
    delegation_log: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# DelegatedAgent
# ---------------------------------------------------------------------------

class DelegatedAgent:
    """An agent with cryptographic identity and delegation.

    Wraps an AgentKeyPair with delegation state. Created by
    DelegatedGraph.add_agent() - not instantiated directly.
    """

    def __init__(
        self,
        name: str,
        keypair: AgentKeyPair,
        delegation: Delegation,
        root_identity: AgentIdentity,
    ):
        self.name = name
        self.keypair = keypair
        self.delegation = delegation
        self.root_identity = root_identity
        self.history: list[dict] = []

    @property
    def did(self) -> str:
        return self.keypair.identity().did

    @property
    def identity(self) -> AgentIdentity:
        return self.keypair.identity()

    def create_proof(self, action: str, args: dict | None = None) -> McpProof:
        """Create an MCP proof for a tool call."""
        args = args or {}
        return McpProof.create(
            self.keypair, action, json.dumps(args), self.delegation
        )

    def verify_action(self, action: str, args: dict | None = None):
        """Verify that this agent can perform the given action.

        Returns (invoker_did, root_did, chain, depth).
        Raises ValueError if delegation doesn't allow it.
        """
        args = args or {}
        invocation = Invocation.create(
            self.keypair, action, json.dumps(args), self.delegation
        )
        return verify_invocation(invocation, self.identity, self.root_identity)

    def __repr__(self) -> str:
        return f"DelegatedAgent(name='{self.name}', did='{self.did}')"


# ---------------------------------------------------------------------------
# DelegatedGraph
# ---------------------------------------------------------------------------

class DelegatedGraph:
    """Manages delegation chains for a LangGraph workflow.

    The root authority (human or system) creates a DelegatedGraph,
    then adds agents with scoped permissions. Each agent gets a
    keypair and delegation chain automatically.

    Usage:

        root = AgentKeyPair.generate()
        graph = DelegatedGraph(root)

        researcher = graph.add_agent(
            "researcher",
            scope=["search", "analyze"],
            max_cost=5.0,
            expires_in_hours=24,
        )

        # Use @delegated_node(graph, researcher) on your node functions
    """

    def __init__(self, root_keypair: AgentKeyPair):
        self.root_keypair = root_keypair
        self.root_identity = root_keypair.identity()
        self.agents: dict[str, DelegatedAgent] = {}
        self._revoked: set[str] = set()

    @property
    def root_did(self) -> str:
        return self.root_identity.did

    def add_agent(
        self,
        name: str,
        scope: list[str] | None = None,
        max_cost: float | None = None,
        expires_in_hours: int | None = None,
        resource: str | None = None,
    ) -> DelegatedAgent:
        """Create a new agent with a delegation from the root.

        Args:
            name: Agent name (for display and lookup).
            scope: Allowed node actions (e.g. ["search", "analyze"]).
            max_cost: Maximum cost per action.
            expires_in_hours: Delegation expiry.
            resource: Resource glob pattern.

        Returns:
            DelegatedAgent with keypair and delegation chain.
        """
        keypair = AgentKeyPair.generate()
        caveats = _build_caveats(scope, max_cost, expires_in_hours, resource)
        delegation = Delegation.create_root(
            self.root_keypair, keypair.identity().did, json.dumps(caveats)
        )
        agent = DelegatedAgent(name, keypair, delegation, self.root_identity)
        self.agents[name] = agent
        return agent

    def sub_delegate(
        self,
        from_agent: DelegatedAgent,
        name: str,
        scope: list[str] | None = None,
        max_cost: float | None = None,
    ) -> DelegatedAgent:
        """Create a sub-agent with narrower delegation from an existing agent.

        The sub-agent inherits the parent's caveats plus any additional
        restrictions. Authority can only narrow, never widen.
        """
        keypair = AgentKeyPair.generate()
        caveats = _build_caveats(scope, max_cost)
        delegation = Delegation.delegate(
            from_agent.keypair, keypair.identity().did,
            json.dumps(caveats), from_agent.delegation
        )
        agent = DelegatedAgent(name, keypair, delegation, self.root_identity)
        self.agents[name] = agent
        return agent

    def get_agent(self, name: str) -> DelegatedAgent:
        """Look up an agent by name."""
        agent = self.agents.get(name)
        if agent is None:
            raise ValueError(f"No agent named '{name}' in this graph")
        return agent

    def revoke(self, agent: DelegatedAgent):
        """Revoke an agent's delegation. Cascades to any sub-delegates."""
        self._revoked.add(agent.delegation.content_hash())

    def is_revoked(self, agent: DelegatedAgent) -> bool:
        return agent.delegation.content_hash() in self._revoked

    def verify_node(self, agent: DelegatedAgent, action: str, args: dict | None = None) -> NodeResult:
        """Verify delegation and return state updates for a node.

        On success, returns delegation metadata to merge into graph state.
        On failure, returns an error in delegation_error.
        """
        if self.is_revoked(agent):
            return NodeResult(
                delegation_agent=agent.name,
                delegation_did=agent.did,
                delegation_error=f"Agent '{agent.name}' delegation has been revoked",
            )

        try:
            invoker_did, root_did, chain, depth = agent.verify_action(action, args)
        except ValueError as e:
            return NodeResult(
                delegation_agent=agent.name,
                delegation_did=agent.did,
                delegation_error=str(e),
            )

        entry = {
            "agent": agent.name,
            "did": agent.did,
            "action": action,
            "chain": chain,
            "depth": depth,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        agent.history.append(entry)

        return NodeResult(
            delegation_agent=agent.name,
            delegation_did=invoker_did,
            delegation_root_did=root_did,
            delegation_chain=chain,
            delegation_depth=depth,
            delegation_error=None,
            delegation_log=[entry],
        )

    def audit_log(self) -> list[dict]:
        """Get a combined, time-sorted audit log from all agents."""
        entries = []
        for agent in self.agents.values():
            for entry in agent.history:
                entries.append({"agent": agent.name, "did": agent.did, **entry})
        entries.sort(key=lambda e: e["timestamp"])
        return entries


# ---------------------------------------------------------------------------
# @delegated_node decorator
# ---------------------------------------------------------------------------

def delegated_node(graph: DelegatedGraph, agent: DelegatedAgent, action: str | None = None):
    """Decorator that gates a LangGraph node behind delegation verification.

    Before the wrapped node function executes, the agent's delegation
    is verified for the given action. If verification fails, the node
    returns an error in the delegation state instead of raising.

    The action defaults to the function name if not provided.

    Usage:

        @delegated_node(graph, researcher)
        def search_node(state: MyState) -> dict:
            # Only runs if researcher has "search_node" in scope
            return {"results": do_search(state["query"])}

        @delegated_node(graph, researcher, action="search")
        def search_node(state: MyState) -> dict:
            # Uses "search" as the action name for caveat checking
            return {"results": do_search(state["query"])}

    Args:
        graph: The DelegatedGraph managing delegation chains.
        agent: The DelegatedAgent whose delegation to verify.
        action: Override the action name (defaults to function name).
    """
    def decorator(func: Callable) -> Callable:
        node_action = action or func.__name__

        @functools.wraps(func)
        def wrapper(state: dict, *args, **kwargs) -> dict:
            # Verify delegation
            result = graph.verify_node(agent, node_action)

            if result.get("delegation_error"):
                # Return error state without executing the node
                return dict(result)

            # Delegation verified - execute the node
            node_output = func(state, *args, **kwargs)

            # Merge delegation metadata into node output
            if isinstance(node_output, dict):
                merged = dict(result)
                merged.update(node_output)
                return merged

            return dict(result)

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_caveats(
    scope: list[str] | None = None,
    max_cost: float | None = None,
    expires_in_hours: int | None = None,
    resource: str | None = None,
) -> list[dict]:
    caveats = []
    if scope:
        caveats.append({"type": "action_scope", "value": scope})
    if max_cost is not None:
        caveats.append({"type": "max_cost", "value": max_cost})
    if expires_in_hours is not None:
        expiry = (
            datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        caveats.append({"type": "expires_at", "value": expiry})
    if resource:
        caveats.append({"type": "resource", "value": resource})
    return caveats
