# src/nxp/orchestration/durable.py
"""
NXP Durable DAG Workflow Engine & Event Sourcing Checkpointer
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from typing import Any, Callable, Dict, List, Optional


class EventStore:
    """Append-only event log for durable step checkpointing."""
    def __init__(self):
        self.events: List[Dict[str, Any]] = []

    def record_step(self, workflow_id: str, step_name: str, result: Any) -> None:
        event = {
            "timestamp": time.time(),
            "workflow_id": workflow_id,
            "step_name": step_name,
            "result": result
        }
        self.events.append(event)

    def get_step_result(self, workflow_id: str, step_name: str) -> Optional[Any]:
        for evt in self.events:
            if evt["workflow_id"] == workflow_id and evt["step_name"] == step_name:
                return evt["result"]
        return None


class DurableDAG:
    """
    Durable DAG workflow engine. Checkpoints completed node execution outputs to an EventStore.
    If execution restarts, cached checkpoint outputs are re-hydrated without re-running side effects.
    """
    def __init__(self, workflow_id: str, event_store: Optional[EventStore] = None):
        self.workflow_id = workflow_id
        self.event_store = event_store or EventStore()
        self.steps: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}

    def step(self, name: str, func: Callable[[Dict[str, Any]], Dict[str, Any]]) -> DurableDAG:
        """Register a workflow step node."""
        self.steps[name] = func
        return self

    async def execute(self, initial_state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the DAG workflow step-by-step with event checkpointing."""
        state = dict(initial_state)

        for step_name, func in self.steps.items():
            # Check if step result was previously checkpointed
            cached_result = self.event_store.get_step_result(self.workflow_id, step_name)
            
            if cached_result is not None:
                print(f"[DurableDAG Checkpoint] Rehydrated cached result for step '{step_name}' from EventStore.")
                state.update(cached_result)
                continue

            print(f"[DurableDAG Execution] Running step '{step_name}'...")
            if inspect.iscoroutinefunction(func):
                result = await func(state)
            else:
                result = func(state)

            if isinstance(result, dict):
                state.update(result)

            # Record event checkpoint
            self.event_store.record_step(self.workflow_id, step_name, result)
            print(f"[DurableDAG Event] Recorded checkpoint for step '{step_name}'.")

        return state
