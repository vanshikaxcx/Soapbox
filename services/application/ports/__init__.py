"""Protocols consumed by application or transport code.

The ports WP-02/08/09 use live in ``core`` and are re-exported here, so callers
keep writing ``from services.application.ports import StateStore`` regardless of
how the package is laid out internally.

``IdFactory`` and ``IdGenerator`` are deliberately both present and are *not*
duplicates: ``IdGenerator.new_id()`` mints an opaque request id for the baseline
transport, while ``IdFactory.new_id(prefix)`` mints a typed domain id whose
prefix the caller chooses. The names are close enough to be mistaken for each
other, so anything depending on the prefix must take ``IdFactory``.
"""

from services.application.ports.core import (
    Action,
    Clock,
    Condition,
    ConditionFailed,
    IdFactory,
    Key,
    MerchantPort,
    PolicyPort,
    StateStore,
    Write,
    read,
)
from services.application.ports.id_generator import IdGenerator

__all__ = [
    "Action",
    "Clock",
    "Condition",
    "ConditionFailed",
    "IdFactory",
    "IdGenerator",
    "Key",
    "MerchantPort",
    "PolicyPort",
    "StateStore",
    "Write",
    "read",
]
