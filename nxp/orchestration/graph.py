# graph.py
"""
NXP Graph Engineering Module
Implements State Graph workflows, node execution routines, conditional routing, and state machine compilation.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List, Optional, Union

START = "__start__"
END = "__end__"


class StateGraph:
    """
    StateGraph allows developers to build state-machine workflows (LangGraph style).
    Nodes process and update shared state dicts, while edges route flow conditionally.
    """
    def __init__(self, state_schema: Optional[type] = None):
        self.state_schema = state_schema
        self.nodes: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}
        self.edges: Dict[str, List[str]] = {}
        self.conditional_edges: Dict[str, Tuple[Callable[[Dict[str, Any]], str], Dict[str, str]]] = {}
        self.entry_point: Optional[str] = None

    def add_node(self, name: str, func: Callable[[Dict[str, Any]], Dict[str, Any]]) -> StateGraph:
        """Add an execution node to the graph state machine."""
        if name in (START, END):
            raise ValueError(f"Node name cannot be reserved string '{name}'")
        self.nodes[name] = func
        return self

    def set_entry_point(self, key: str) -> StateGraph:
        """Set the initial node to execute when starting the state machine graph."""
        if key not in self.nodes:
            raise ValueError(f"Entry point node '{key}' must be added to graph first.")
        self.entry_point = key
        return self

    def add_edge(self, start_key: str, end_key: str) -> StateGraph:
        """Add a static directed transition edge between two nodes."""
        if start_key not in self.nodes and start_key != START:
            raise ValueError(f"Start node '{start_key}' not found in graph.")
        if end_key not in self.nodes and end_key != END:
            raise ValueError(f"Target node '{end_key}' not found in graph.")

        if start_key == START:
            self.set_entry_point(end_key)
            return self

        if start_key not in self.edges:
            self.edges[start_key] = []
        self.edges[start_key].append(end_key)
        return self

    def add_conditional_edges(
        self,
        source_key: str,
        condition_func: Callable[[Dict[str, Any]], str],
        path_map: Dict[str, str]
    ) -> StateGraph:
        """
        Add dynamic conditional routing. The condition_func inspects state and returns a path key.
        The path_map maps the key to the destination node name or END.
        """
        if source_key not in self.nodes:
            raise ValueError(f"Source node '{source_key}' not found in graph.")
        self.conditional_edges[source_key] = (condition_func, path_map)
        return self

    def compile(self) -> CompiledGraph:
        """Compile the StateGraph into an executable workflow runner."""
        if not self.entry_point:
            raise ValueError("Graph missing entry point. Call set_entry_point() or add_edge(START, 'first_node')")
        return CompiledGraph(self)


class CompiledGraph:
    """Executable workflow engine compiled from a StateGraph."""

    def __init__(self, graph: StateGraph):
        self.graph = graph

    async def invoke(self, initial_state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the state graph workflow asynchronously until END is reached."""
        state = dict(initial_state)
        current_node = self.graph.entry_point

        print(f"[StateGraph] Beginning workflow execution at entry point: '{current_node}'")

        step_count = 0
        max_steps = 100  # Guard against infinite routing loops

        while current_node and current_node != END and step_count < max_steps:
            step_count += 1
            node_func = self.graph.nodes[current_node]

            print(f"[StateGraph Step {step_count}] Executing Node: '{current_node}'")
            
            # Execute node function (supports both sync and async functions)
            if inspect.iscoroutinefunction(node_func):
                result_update = await node_func(state)
            else:
                result_update = node_func(state)

            # Update state dictionary
            if isinstance(result_update, dict):
                state.update(result_update)

            # Resolve next node transition
            next_node = None

            # 1. Check for conditional edge routing
            if current_node in self.graph.conditional_edges:
                cond_func, path_map = self.graph.conditional_edges[current_node]
                path_key = cond_func(state)
                next_node = path_map.get(path_key, END)
                print(f"[StateGraph Router] Conditional edge from '{current_node}' evaluated route '{path_key}' -> next node: '{next_node}'")

            # 2. Check for static direct edges
            elif current_node in self.graph.edges:
                next_node = self.graph.edges[current_node][0]
                print(f"[StateGraph Transition] Direct edge from '{current_node}' -> '{next_node}'")

            else:
                # Terminal node with no outgoing edges defaults to END
                next_node = END

            current_node = next_node

        print(f"[StateGraph Workflow] Execution completed in {step_count} steps.")
        return state
