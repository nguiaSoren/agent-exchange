"""Canonical types + the model-backend boundary."""

from .backend import (
    PRICE_PER_MTOK,
    PROVIDERS,
    MockBackend,
    ModelBackend,
    OpenAICompatBackend,
    make_backend,
)
from .types import CompletionResult, FinishReason, Message, Role, Usage

__all__ = [
    "Message",
    "Role",
    "Usage",
    "CompletionResult",
    "FinishReason",
    "ModelBackend",
    "OpenAICompatBackend",
    "MockBackend",
    "make_backend",
    "PROVIDERS",
    "PRICE_PER_MTOK",
]
