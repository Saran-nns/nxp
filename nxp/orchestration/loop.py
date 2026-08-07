# loop.py
"""
NXP Loop Engineering Module
Implements Feedback Loops, Reflexive Agents, Self-Correcting Execution, and Evaluator-Optimizer loops.
"""

from __future__ import annotations

import inspect
import trace
from typing import Any, Callable, Dict, List, Optional, Tuple


class FeedbackLoop:
    """
    FeedbackLoop continuously executes a candidate generator task, passes the output to an evaluator,
    and feeds any error feedback or quality scores back into the next iteration context until convergence.
    """
    def __init__(
        self,
        generator: Callable[[str, Optional[str]], Any],
        evaluator: Callable[[Any], Tuple[bool, str]],
        max_iterations: int = 5,
        force_full_iterations: bool = False
    ):
        self.generator = generator
        self.evaluator = evaluator
        self.max_iterations = max_iterations
        self.force_full_iterations = force_full_iterations

    async def run(self, initial_prompt: str) -> Dict[str, Any]:
        """Run the feedback loop until evaluator passes or max_iterations reached."""
        feedback = None
        current_attempt = 0
        history: List[Dict[str, Any]] = []

        print(f"[FeedbackLoop] Starting loop for prompt: '{initial_prompt}' (Max iterations: {self.max_iterations})")

        while current_attempt < self.max_iterations:
            current_attempt += 1
            print(f"\n[FeedbackLoop Iteration {current_attempt}/{self.max_iterations}] Running generator...")
            
            # Execute generator (supports sync & async)
            if inspect.iscoroutinefunction(self.generator):
                output = await self.generator(initial_prompt, feedback)
            else:
                output = self.generator(initial_prompt, feedback)

            # Evaluate output
            if inspect.iscoroutinefunction(self.evaluator):
                passed, eval_feedback = await self.evaluator(output)
            else:
                passed, eval_feedback = self.evaluator(output)

            history.append({
                "iteration": current_attempt,
                "output": output,
                "passed": passed,
                "feedback": eval_feedback
            })

            print(f"[FeedbackLoop Evaluator] Iteration {current_attempt} -> Passed: {passed} | Feedback: '{eval_feedback}'")

            if passed and not self.force_full_iterations:
                print(f"[FeedbackLoop Converged] Task passed evaluation in {current_attempt} iterations!")
                return {
                    "status": "success",
                    "final_output": output,
                    "iterations": current_attempt,
                    "history": history
                }

            # Update feedback for next iteration loop
            feedback = eval_feedback

        print(f"[FeedbackLoop Completed] Executed full {self.max_iterations} iterations successfully.")
        return {
            "status": "success" if history[-1]["passed"] else "completed",
            "final_output": history[-1]["output"],
            "iterations": current_attempt,
            "history": history
        }



class ReflexiveAgent:
    """
    A Reflexive Agent catches tool execution exceptions, inspects tracebacks, and automatically
    feeds error messages back to the cognitive reasoning prompt for self-correction.
    """
    def __init__(self, agent_instance: Any, max_retries: int = 3):
        self.agent = agent_instance
        self.max_retries = max_retries

    async def execute_with_self_correction(
        self,
        task_func: Callable[..., Any],
        *args: Any,
        **kwargs: Any
    ) -> Any:
        """Execute task function with automatic exception intercept and feedback self-correction."""
        attempts = 0
        error_context = ""

        while attempts < self.max_retries:
            attempts += 1
            try:
                print(f"[ReflexiveAgent Attempt {attempts}] Executing task...")
                if inspect.iscoroutinefunction(task_func):
                    return await task_func(*args, **kwargs)
                else:
                    return task_func(*args, **kwargs)
            except Exception as exc:
                error_context = f"Previous attempt failed with error: {type(exc).__name__}: {str(exc)}"
                print(f"[ReflexiveAgent Self-Correction] Caught exception: {error_context}. Feeding back to context...")
                if "feedback_history" in kwargs:
                    kwargs["feedback_history"].append(error_context)
                else:
                    kwargs["error_context"] = error_context

        raise RuntimeError(f"ReflexiveAgent failed after {self.max_retries} self-correction attempts. Last error: {error_context}")
