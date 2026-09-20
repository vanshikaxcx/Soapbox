"""What the offer/guidance projection promises (WP-07).

Two properties, and every test here is one of them made observable.

*An older document cannot overwrite a newer one.* Asserted on what the index
holds afterwards and on how many writes it took -- ``puts`` is an effect count,
and an ignored delivery that still wrote would pass a "the newest version is
indexed" check while doing exactly the thing the rule forbids.

*An outage makes the read slower, not wrong.* Asserted by running the same
retrieval twice, once with the index up and once with it dark, and requiring the
two to return the same canonical records. A test that only checked the fallback
returned *something* would pass against a fallback that returned the wrong rows.

``Search`` stands in for a canonical row because it is a real record with a real
``version`` and it is what ``offers-v1`` projects. The ``SEARCH#`` key shape is
this test's own: WP-07 does not own it, and no merged module writes one yet.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from services.application.fakes import MemorySearchIndex, MemoryStore
from services.application.indexer import (
    DEFAULT_LIMIT,
    IndexAction,
    Indexed,
    ProjectionIndexer,
    ProjectionReader,
    ReadSource,
    Retrieval,
    supersedes,
)
from services.application.ports import Key, Write
from services.application.ports.index import IndexedDocument, IndexName, IndexUnavailable
from services.domain.ids import Mode
from services.domain.search import Search

MOMENT = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)
OWNER = "owner-0001"


def search_key(search_id: str) -> Key:
    return (f"SEARCH#{search_id}", "SEARCH")


def canonical_search(search_id: str, *, version: int = 1, owner: str = OWNER) -> Search:
    return Search(
        search_id=search_id,
        owner_id=owner,
        intent_id="intent-0001",
        intent_revision=1,
        location="560001",
        mode=Mode.FIXTURE,
        started_at=MOMENT,
        version=version,
    )


def document(
    search_id: str,
    *,
    version: int = 1,
    owner: str = OWNER,
    terms: tuple[str, ...] = ("rice",),
    index: IndexName = IndexName.OFFERS,
) -> IndexedDocument:
    return IndexedDocument(
        index=index,
        document_id=search_id,
        owner_id=owner,
        version=version,
        key=search_key(search_id),
        terms=terms,
    )


@pytest.fixture
def index() -> MemorySearchIndex:
    return MemorySearchIndex()


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


def seed(store: MemoryStore, *searches: Search) -> None:
    store.transact(
        [
            Write(key=search_key(s.search_id), item=s, reason="a canonical row already committed")
            for s in searches
        ]
    )


def held(index: MemorySearchIndex, search_id: str) -> int | None:
    return index.version_of(IndexName.OFFERS, search_id)


# -- version ordering ------------------------------------------------------


def test_a_document_the_index_has_never_seen_is_indexed(index: MemorySearchIndex) -> None:
    outcome = ProjectionIndexer(index=index).project(document("sr-000001", version=1))
    assert outcome == Indexed("sr-000001", IndexAction.INDEXED, 1)
    assert held(index, "sr-000001") == 1


def test_a_newer_version_replaces_the_one_indexed(index: MemorySearchIndex) -> None:
    indexer = ProjectionIndexer(index=index)
    indexer.project(document("sr-000001", version=2))
    outcome = indexer.project(document("sr-000001", version=5))
    assert outcome == Indexed("sr-000001", IndexAction.INDEXED, 5)
    assert held(index, "sr-000001") == 5
    assert index.puts == 2


def test_an_older_version_cannot_overwrite_a_newer_one(index: MemorySearchIndex) -> None:
    """The rule, stated as the thing a shopper would otherwise see.

    A superseded price arriving late and winning is the failure; the count of
    writes is what proves it never reached the index, rather than reaching it
    and being repaired afterwards.
    """
    indexer = ProjectionIndexer(index=index)
    indexer.project(document("sr-000001", version=5))
    outcome = indexer.project(document("sr-000001", version=2))
    assert outcome == Indexed("sr-000001", IndexAction.IGNORED_AS_NOT_NEWER, 5)
    assert held(index, "sr-000001") == 5
    assert index.puts == 1


def test_the_same_version_delivered_again_is_not_rewritten(index: MemorySearchIndex) -> None:
    """At-least-once delivery, absorbed without the indexer remembering anything."""
    indexer = ProjectionIndexer(index=index)
    indexer.project(document("sr-000001", version=3))
    outcome = indexer.project(document("sr-000001", version=3))
    assert outcome == Indexed("sr-000001", IndexAction.IGNORED_AS_NOT_NEWER, 3)
    assert index.puts == 1


def test_out_of_order_deliveries_settle_on_the_highest_version(index: MemorySearchIndex) -> None:
    """The routine case: SQS is unordered, so v3 before v1 before v2 is traffic."""
    indexer = ProjectionIndexer(index=index)
    for version in (3, 1, 2):
        indexer.project(document("sr-000001", version=version))
    assert held(index, "sr-000001") == 3
    assert index.puts == 1


def test_one_document_does_not_shadow_another(index: MemorySearchIndex) -> None:
    """Ordering is per document, not a high-water mark across the index."""
    indexer = ProjectionIndexer(index=index)
    indexer.project(document("sr-000001", version=9))
    outcome = indexer.project(document("sr-000002", version=1))
    assert outcome == Indexed("sr-000002", IndexAction.INDEXED, 1)
    assert held(index, "sr-000002") == 1


def test_an_outage_while_reading_the_current_version_writes_nothing(
    index: MemorySearchIndex,
) -> None:
    """Not knowing what is indexed is not permission to overwrite it."""
    indexer = ProjectionIndexer(index=index)
    indexer.project(document("sr-000001", version=5))
    index.go_dark("cluster_red")

    outcome = indexer.project(document("sr-000001", version=2))

    assert outcome == IndexUnavailable(index=IndexName.OFFERS, error_code="cluster_red")
    assert index.puts == 1
    index.recover()
    assert held(index, "sr-000001") == 5


def test_a_read_fault_alone_still_stops_an_older_document_landing(
    index: MemorySearchIndex,
) -> None:
    """The one shape in which a collapsed outage would corrupt the index.

    ``go_dark`` fails the write as well, so a version check that treated an
    outage as "nothing is indexed" would still be saved by the write failing --
    for the wrong reason. Here reads fail and writes would land, so the only
    thing standing between an older document and the index is the indexer
    refusing to act on an answer it did not get.
    """
    indexer = ProjectionIndexer(index=index)
    indexer.project(document("sr-000001", version=5))
    index.stop_answering_reads("read_timeout")

    outcome = indexer.project(document("sr-000001", version=2))

    assert outcome == IndexUnavailable(index=IndexName.OFFERS, error_code="read_timeout")
    assert index.puts == 1
    index.recover()
    assert held(index, "sr-000001") == 5


def test_versions_of_two_different_documents_cannot_be_compared() -> None:
    """A routing bug, not a lost race, so it raises rather than returning."""
    with pytest.raises(ValueError, match="versions compare within one document"):
        supersedes(document("sr-000001", version=9), document("sr-000002", version=1))


def test_the_same_document_in_two_indices_is_not_the_same_document() -> None:
    with pytest.raises(ValueError, match="versions compare within one document"):
        supersedes(
            document("sr-000001", version=9),
            document("sr-000001", version=1, index=IndexName.GUIDANCE),
        )


# -- canonical fallback ----------------------------------------------------


def retrieve(
    store: MemoryStore,
    index: MemorySearchIndex,
    *,
    terms: Sequence[str] = ("rice",),
    canonical_prefix: str = "SEARCH#",
    limit: int = DEFAULT_LIMIT,
) -> Retrieval[Search]:
    """One query, so every test below differs only in the data and the outage."""
    return ProjectionReader(store=store, index=index).retrieve(
        Search,
        index=IndexName.OFFERS,
        owner_id=OWNER,
        terms=terms,
        canonical_prefix=canonical_prefix,
        limit=limit,
    )


def ids(result: Retrieval[Search]) -> list[str]:
    return [record.search_id for record in result.records]


def test_an_index_hit_is_answered_from_the_canonical_row(
    store: MemoryStore, index: MemorySearchIndex
) -> None:
    seed(store, canonical_search("sr-000001", version=4))
    ProjectionIndexer(index=index).project(document("sr-000001", version=4))

    result = retrieve(store, index)

    assert result.source is ReadSource.INDEX
    assert result.records == (canonical_search("sr-000001", version=4),)


def test_an_outage_serves_the_same_records_from_canonical_state(
    store: MemoryStore, index: MemorySearchIndex
) -> None:
    """ "Slower, not wrong", asserted as an equality rather than as a shape.

    The same query runs twice against the same data. If the fallback returned
    different rows -- or none -- this fails, which a "the fallback returned
    something" assertion would not.
    """
    seed(store, canonical_search("sr-000001", version=4), canonical_search("sr-000002", version=2))
    indexer = ProjectionIndexer(index=index)
    indexer.project(document("sr-000001", version=4))
    indexer.project(document("sr-000002", version=2))

    served_by_index = retrieve(store, index)
    index.go_dark()
    served_by_canonical = retrieve(store, index)

    assert served_by_index.source is ReadSource.INDEX
    assert served_by_canonical.source is ReadSource.CANONICAL_FALLBACK
    assert served_by_canonical.records == served_by_index.records
    assert index.searches == 1, "the dark index was queried instead of being fallen back from"


def test_a_document_left_behind_at_an_old_version_cannot_serve_stale_data(
    store: MemoryStore, index: MemorySearchIndex
) -> None:
    """The reload, made visible: the hit says v1, the answer is the canonical v6.

    This is why ``IndexedDocument`` carries no body. There is nothing stale to
    return even when the projection is far behind -- the hit is a pointer, and
    the row it points at is read fresh every time.
    """
    seed(store, canonical_search("sr-000001", version=6))
    ProjectionIndexer(index=index).project(document("sr-000001", version=1))

    result = retrieve(store, index)

    assert [record.version for record in result.records] == [6]


def test_a_hit_whose_canonical_row_has_gone_is_dropped(
    store: MemoryStore, index: MemorySearchIndex
) -> None:
    """The index is rebuildable and may name a row that no longer exists."""
    seed(store, canonical_search("sr-000001"))
    indexer = ProjectionIndexer(index=index)
    indexer.project(document("sr-000001"))
    indexer.project(document("sr-000002"))

    assert ids(retrieve(store, index)) == ["sr-000001"]


def test_an_index_that_matches_nothing_is_not_an_outage(
    store: MemoryStore, index: MemorySearchIndex
) -> None:
    """An empty answer is an answer, and must not trigger the fallback scan."""
    seed(store, canonical_search("sr-000001"))
    ProjectionIndexer(index=index).project(document("sr-000001", terms=("atta",)))

    result = retrieve(store, index)

    assert result.source is ReadSource.INDEX
    assert result.records == ()


def test_the_fallback_may_return_more_than_the_index_would(
    store: MemoryStore, index: MemorySearchIndex
) -> None:
    """Recorded because it is the documented shape of the degradation.

    The fallback has no analysed fields to narrow with, so it returns everything
    under the scoped prefix. Wider is slower; narrower would be wrong, and the
    direction of that inequality is the whole guarantee.
    """
    seed(store, canonical_search("sr-000001"), canonical_search("sr-000002"))
    indexer = ProjectionIndexer(index=index)
    indexer.project(document("sr-000001", terms=("rice",)))
    indexer.project(document("sr-000002", terms=("atta",)))

    served_by_index = retrieve(store, index)
    index.go_dark()
    served_by_canonical = retrieve(store, index)

    assert ids(served_by_index) == ["sr-000001"]
    assert ids(served_by_canonical) == ["sr-000001", "sr-000002"]


def test_the_fallback_reads_only_the_prefix_it_was_scoped_to(
    store: MemoryStore, index: MemorySearchIndex
) -> None:
    """A prefix scan has no filters of its own, so the key has to carry them."""
    seed(store, canonical_search("sr-000001"))
    store.transact(
        [
            Write(
                key=("OTHER#sr-000002", "SEARCH"),
                item=canonical_search("sr-000002"),
                reason="a row outside the scoped prefix",
            )
        ]
    )
    index.go_dark()

    assert ids(retrieve(store, index)) == ["sr-000001"]


def test_the_fallback_is_bounded_by_the_limit(store: MemoryStore, index: MemorySearchIndex) -> None:
    """An unbounded scan behind a shopper-facing read is what O-3 rules out."""
    seed(store, *(canonical_search(f"sr-00000{n}") for n in range(1, 6)))
    index.go_dark()

    assert len(retrieve(store, index, limit=2).records) == 2
