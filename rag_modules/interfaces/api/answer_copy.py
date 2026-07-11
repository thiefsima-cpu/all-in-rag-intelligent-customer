"""API helpers for answer-workflow copy overrides."""

from __future__ import annotations


def answer_failed_message_from_system(system: object) -> str | None:
    serving_runtime = getattr(system, "serving_runtime", None)
    answer_workflow = getattr(serving_runtime, "answer_workflow", None)
    answer_workflow_copy = getattr(answer_workflow, "answer_workflow_copy", None)
    message = getattr(answer_workflow_copy, "answer_failed", None)
    if message is None:
        return None
    text = str(message)
    return text if text.strip() else None


__all__ = ["answer_failed_message_from_system"]
