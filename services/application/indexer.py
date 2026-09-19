"""The offer/guidance projection: version ordering in, canonical fallback out (WP-07).

Two rules, and they are the same rule seen from either end of the projection.

**An older document must not overwrite a newer one.** Projections arrive through
Streams -> EventBridge -> SQS. That path is at-least-once and unordered, so v3
arriving before v2 is routine traffic, not a fault. Without an ordering check the
index would settle on whichever delivery happened to land last, and a search
would quietly return a shopper a price that had already been superseded. SPEC:
"Indexer ignores older versions."

**An index that cannot answer does not fail the read.** WP-07's failure table:
``index outage | canonical fallback serves the read | slower, not wrong``. The
fallback scans the canonical prefix instead of querying, and returns the same
canonical records. It may return *more* of them than the index would -- it has
no analysed fields to narrow with -- and it can never return fewer, or a record
the index would not have pointed at. Losing precision is slower; losing a record
would be wrong, and that is the distinction the two words are drawing.

**Why this is not ``services/domain/search.py:is_current``.** That function is
already version-ordering logic in this codebase and it was the first thing
considered here, because the same rule implemented twice is a defect. They turn
out to be different questions and merging them would break both:

* ``is_current(search, intent_revision)`` is *equality* against a canonical
  counter -- a search bound to revision 2 is stale forever once a repair makes
  the intent revision 3, and it must never become current again.
* ordering here is *strictly greater* between two projections of the same row --
  a document at v5 must replace one at v3, precisely because they are unequal.

An index that used equality would refuse every legitimate update; a search that
used ordering would let an abandoned comparison become current again. What they
share is the principle, not the predicate: a projection is only ever as good as
the canonical version it was taken from. The principle is honoured here by
``version`` being the canonical aggregate version rather than a counter this
module keeps, and by every read reloading the canonical row before returning it.

Nothing in this module decides anything about a job. ``services/domain/jobs.py``
remains the only place a job transition is decided; an indexer run that is
dispatched as a job reports its outcome and lets the controller do that.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from services.application.ports import StateStore, read
from services.application.ports.index import (
    IndexedDocument,
    IndexName,
    IndexUnavailable,
    SearchIndex,
)

#: How many canonical rows one retrieval will resolve. Bounded on both paths:
#: the fallback is a prefix scan, and an unbounded scan behind a shopper-facing
#: read is the thing WP-07's O-3 rules out everywhere except operator tools.
DEFAULT_LIMIT: Final = 50


def supersedes(incoming: IndexedDocument, current: IndexedDocument) -> bool:
    """Whether ``incoming`` may replace the document the index already holds.

    Strictly greater, so a redelivery of the version already indexed is ignored
    rather than rewritten. That makes indexing idempotent under at-least-once
    delivery without the indexer having to remember what it has seen.

    Raises on a mismatched identity. Comparing the versions of two different
    documents is meaningless, and a caller that does it has a routing bug rather
    than a lost race -- there is no 409 to render and nothing to retry, so it
    raises for the same reason ``reject_duplicate_keys`` does.
    """
    if incoming.index is not current.index or incoming.document_id != current.document_id:
        raise ValueError(
            f"cannot order {incoming.index}/{incoming.document_id} against "
            f"{current.index}/{current.document_id}; versions compare within one document"
        )
    return incoming.version > current.version


class IndexAction(StrEnum):
    """What the indexer did, named rather than inferred from the version."""

    INDEXED = "indexed"
    #: Older *or equal*. Both are the same non-event: the index already holds
    #: something at least as good, so there is nothing to do and nothing wrong.
    IGNORED_AS_NOT_NEWER = "ignored_as_not_newer"


@dataclass(frozen=True, slots=True)
class Indexed:
    """The outcome of one projection delivery.

    ``version`` is what the index holds *afterwards*, not what arrived. On an
    ignored delivery those differ, and reporting the arriving version would tell
    an operator the opposite of what happened.
    """

    document_id: str
    action: IndexAction
    version: int


class ReadSource(StrEnum):
    """Which path served a retrieval.

    Reported rather than logged, because "slower, not wrong" is only observable
    if a caller can see which of the two it got. A demo trace that cannot show
    the fallback being used cannot show that it preserved the answer.
    """

    INDEX = "index"
    CANONICAL_FALLBACK = "canonical_fallback"


@dataclass(frozen=True, slots=True)
class Retrieval[T]:
    """Canonical records, and which path found them.

    The records are always read from the ``StateStore``, on both paths. An index
    hit is a pointer to a row, never the row -- so a document projected from a
    version that has since moved on cannot serve stale data; it can only point
    at a row that is then read fresh.
    """

    source: ReadSource
    records: tuple[T, ...]


@dataclass(frozen=True, slots=True)
class ProjectionIndexer:
    """Applies a projection delivery to the index, in version order."""

    index: SearchIndex

    def project(self, document: IndexedDocument) -> Indexed | IndexUnavailable:
        """Index ``document`` unless the index already holds it, or something newer."""
        current = self.index.current(document.index, document.document_id)
        if isinstance(current, IndexUnavailable):
            # Not knowing what is indexed is not permission to overwrite it.
            # The delivery is reported unhandled so the source redelivers it.
            return current
        if current is not None and not supersedes(document, current):
            return Indexed(document.document_id, IndexAction.IGNORED_AS_NOT_NEWER, current.version)
        failure = self.index.put(document)
        if failure is not None:
            return failure
        return Indexed(document.document_id, IndexAction.INDEXED, document.version)


@dataclass(frozen=True, slots=True)
class ProjectionReader:
    """Serves a read from the index when it can, and from canonical state when not."""

    store: StateStore
    index: SearchIndex

    def retrieve[T](
        self,
        kind: type[T],
        *,
        index: IndexName,
        owner_id: str,
        terms: Sequence[str],
        canonical_prefix: str,
        limit: int = DEFAULT_LIMIT,
    ) -> Retrieval[T]:
        """Canonical records for this query, whichever path is available.

        ``canonical_prefix`` is what the fallback scans, and the caller is
        responsible for having scoped it to what this owner may see. The index
        applies its owner filter server-side; a prefix scan has no filters to
        apply, so anything that must constrain the fallback has to be in the key.
        Passing a prefix wider than the caller's authority would widen the read
        the moment the cluster went dark, which is a failure mode worth naming.

        A hit whose canonical row has gone is dropped rather than reported: the
        index is rebuildable and may name a row that no longer exists, and an
        empty placeholder in a result set is worse than a shorter result set.
        """
        hits = self.index.search(index, owner_id=owner_id, terms=terms, limit=limit)
        if isinstance(hits, IndexUnavailable):
            source = ReadSource.CANONICAL_FALLBACK
            keys = self.store.keys_matching(canonical_prefix)[:limit]
        else:
            source = ReadSource.INDEX
            keys = [hit.key for hit in hits[:limit]]
        found = (read(self.store, key, kind) for key in keys)
        return Retrieval(source=source, records=tuple(r for r in found if r is not None))


__all__ = [
    "DEFAULT_LIMIT",
    "IndexAction",
    "Indexed",
    "ProjectionIndexer",
    "ProjectionReader",
    "ReadSource",
    "Retrieval",
    "supersedes",
]
