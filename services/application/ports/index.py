"""The offer and guidance index, as the projection needs it (WP-07).

The index is a **projection**, never an authority. SPEC: "Rebuildable offer
search and keyword guidance retrieval; never price/payment authority. Canonical
fallback preserves correctness", and "Reload canonical facts before using index
results." Everything in this port is shaped to make that structural rather than
a habit callers have to remember:

* an ``IndexedDocument`` carries an identity, a version and the **key** of the
  canonical row it projects -- not a copy of that row. There is deliberately no
  body to serve, so a caller cannot answer from the index by accident. It has to
  go back to the ``StateStore``, and the reload is the read.
* an outage is returned as ``IndexUnavailable`` rather than raised, because the
  correct response is to serve the same read from canonical state. A port that
  raised would make "slower" indistinguishable from "broken" at every call site,
  and the natural thing to write around an exception is a failed read.

``version`` is the canonical aggregate version the document was projected from.
It is what makes an out-of-order delivery harmless: projections arrive through
Streams -> EventBridge -> SQS, which is at-least-once and unordered, so the
indexer sees v3 before v2 as a matter of routine, not as a fault.

**Obligations on the future OpenSearch adapter**, stated here rather than
discovered the way ``StateStore.keys_matching`` was:

1. ``search`` and ``current`` return ``IndexUnavailable`` for *every* transport
   or cluster fault -- unreachable, throttled, red, no such index. An adapter
   that lets one of those escape as an exception disables the fallback for that
   one failure mode, which is the failure mode most likely to happen.
2. ``search`` applies the trusted owner and locality filters server-side. The
   canonical fallback scans a prefix the caller has already scoped, so anything
   the index filters and the fallback cannot must be part of the key.
3. ``put`` is last-write-wins on its own. The ordering rule lives in
   ``services/application/indexer.py`` so it is stated once and testable without
   a cluster; the adapter is expected to *also* set ``version_type=external`` so
   two concurrent indexers cannot interleave a read and a write. Two enforcement
   points, one rule -- the second is a guard, not a second decision.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Protocol, runtime_checkable

from pydantic import Field

from services.application.ports.core import Key
from services.domain.errors import DomainError
from services.domain.ids import Id, Record


class IndexName(StrEnum):
    """The two indices SPEC names, with their version suffixes.

    The suffix is part of the name because a reindex creates ``offers-v2`` and
    swaps an alias; a name without one would have to be edited in place, which
    is the thing a rebuildable projection is supposed to avoid.
    """

    OFFERS = "offers-v1"
    GUIDANCE = "guidance-v1"


class IndexedDocument(Record):
    """One projected document: an identity, a version, and where the truth is.

    ``key`` is the canonical ``StateStore`` row this projects. It is the only
    thing a reader is meant to do with a hit -- go and read that row -- so it is
    required rather than optional, and a document that cannot name its canonical
    row cannot be constructed.
    """

    index: IndexName
    document_id: str = Field(min_length=1, max_length=128)
    owner_id: Id
    #: The canonical aggregate version this projection was built from.
    version: int = Field(ge=1)
    key: Key
    #: What the index matches on. Opaque to this layer: WP-06/P2 decide the
    #: analysed fields, and this package consumes the index it is given.
    terms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IndexUnavailable(DomainError):
    """The index could not answer. A normal outcome, not an error path.

    Carries the cluster's own code so an operator can tell a throttle from a red
    index without reading prose. The shopper sees neither: the read is served
    from canonical state and is slower, not wrong.
    """

    code: ClassVar[str] = "index_unavailable"
    index: IndexName
    error_code: str


@runtime_checkable
class SearchIndex(Protocol):
    """OpenSearch in production. Not provisioned yet -- WP-01 owns the cluster."""

    def current(
        self, index: IndexName, document_id: str
    ) -> IndexedDocument | None | IndexUnavailable:
        """What the index holds for this document, or ``None`` if nothing.

        ``None`` and ``IndexUnavailable`` must stay distinct: "nothing is indexed
        yet" means index it, and "I cannot tell you" means do not touch it. An
        adapter that collapsed them into ``None`` would let an outage overwrite a
        newer document with an older one, which is the exact rule this port
        exists to protect.
        """
        ...

    def put(self, document: IndexedDocument) -> None | IndexUnavailable:
        """Store the document, unconditionally. ``None`` means it landed.

        Unconditional by contract: the decision about whether it *should* land
        was already made by the indexer. See obligation 3 in the module
        docstring for the versioning guard the adapter adds underneath.
        """
        ...

    def search(
        self, index: IndexName, *, owner_id: Id, terms: Sequence[str], limit: int
    ) -> list[IndexedDocument] | IndexUnavailable:
        """Documents matching every term, for this owner, most specific first.

        Returns documents rather than records, so the caller still has to reload
        each canonical row. An empty list means the index answered and matched
        nothing, which is not the same as not answering.
        """
        ...


__all__ = [
    "IndexName",
    "IndexUnavailable",
    "IndexedDocument",
    "SearchIndex",
]
