"""The DynamoDB ``StateStore`` (WP-07).

The port is WP-08's; this is the implementation P4 owes it. Three properties of
that port are load-bearing and are not this module's to reinterpret, so each one
is called out where it is implemented:

1. **``ConditionFailed`` is returned, never raised.** Every caller branches on
   the return value and not one of them has an ``except``, so an escaping
   ``ConditionalCheckFailedException`` would not surface as an error -- it would
   unwind through a use case that believed it had committed. That is the failure
   this module exists to prevent, and it is why the mapping is done by error
   code rather than by catching a subclass and hoping.
2. **``transact`` is all-or-none.** Every write goes through
   ``TransactWriteItems``, including the single-write case, because a fast path
   that used ``PutItem`` for one write would be a second code path with
   different failure semantics for the sake of nothing.
3. **``item=None`` deletes**, and the delete is a ``Delete`` inside the same
   transaction, so it lands or fails with everything else.

Records are persisted as their own JSON plus a type tag rather than as mapped
DynamoDB attributes. That is deliberate. DynamoDB returns every number as a
``Decimal``, and ``Record`` is ``strict=True``, so an attribute-mapped read
would hand a ``Decimal`` to a field declared ``int`` and be rejected -- or,
worse, be "fixed" later by relaxing the model or by routing money through
``float``. Validating from JSON keeps ``amount_paise`` an ``int`` on the way
back, because it was never anything else on the way out.
"""

from __future__ import annotations

import functools
import importlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from botocore.exceptions import ClientError
from pydantic import BaseModel

from services.application.ports import (
    Condition,
    ConditionFailed,
    Key,
    Write,
    reject_duplicate_keys,
)

if TYPE_CHECKING:  # pragma: no cover - import exists for the type checker only
    from mypy_boto3_dynamodb.client import DynamoDBClient
    from mypy_boto3_dynamodb.type_defs import (
        AttributeValueTypeDef,
        DeleteTypeDef,
        PutTypeDef,
        TransactWriteItemTypeDef,
    )

#: The table's key attributes. Exported so ``infra/template.yaml`` can be
#: authored against the names the adapter actually uses instead of a copy of
#: them that drifts. Table *naming* is open question O-2 and is not decided here.
PARTITION_ATTRIBUTE: Final = "pk"
SORT_ATTRIBUTE: Final = "sk"

#: The record's own JSON, and the class that has to be asked to parse it.
BODY_ATTRIBUTE: Final = "body"
TYPE_ATTRIBUTE: Final = "type"

#: A mirror of the record's ``version`` field, denormalised to the top level.
#: DynamoDB can only compare an attribute, and ``VERSION_MUST_BE`` compares a
#: version -- so the version has to exist as an attribute. The JSON body stays
#: authoritative; this is derived from it and never read back into a record.
VERSION_ATTRIBUTE: Final = "version"

#: DynamoDB's own ceiling on one transaction. Named so that exceeding it fails
#: with a sentence rather than with a service validation error.
TRANSACTION_LIMIT: Final = 100

#: Only records from this codebase may be rehydrated. A type tag is data read
#: back out of the table, and importing an arbitrary dotted path named by stored
#: data is how a storage layer turns into an execution vector.
_TRUSTED_ROOT: Final = "services."


class TypeTagRefused(ValueError):
    """A stored item named a type that must not, or cannot, be imported.

    Raised rather than returned because it is corruption, not a race: there is
    nothing the caller can retry and no 409 to render. Reading it as ``None``
    would be worse -- an absent record and a corrupt one lead to opposite
    actions, and ``read()`` would quietly treat the corrupt one as "not there".
    """


def type_tag(record: BaseModel) -> str:
    """Name the class precisely enough to find it again, and no more."""
    cls = type(record)
    return f"{cls.__module__}:{cls.__qualname__}"


@functools.cache
def _resolve(tag: str) -> type[BaseModel]:
    module_name, _, qualname = tag.partition(":")
    if not qualname or not module_name.startswith(_TRUSTED_ROOT):
        raise TypeTagRefused(f"refusing to import {tag!r}: not a {_TRUSTED_ROOT}* record")
    resolved: Any = importlib.import_module(module_name)
    for part in qualname.split("."):
        resolved = getattr(resolved, part, None)
        if resolved is None:
            raise TypeTagRefused(f"{tag!r} names nothing importable")
    if not (isinstance(resolved, type) and issubclass(resolved, BaseModel)):
        raise TypeTagRefused(f"{tag!r} is not a record type")
    return resolved


def encode(item: object) -> dict[str, AttributeValueTypeDef]:
    """Render a record as attributes, keeping its numbers the width they are."""
    if not isinstance(item, BaseModel):
        raise TypeError(
            f"cannot store {type(item).__name__}; the store holds records, and a "
            "plain object has no schema to validate on the way back"
        )
    attributes: dict[str, AttributeValueTypeDef] = {
        TYPE_ATTRIBUTE: {"S": type_tag(item)},
        BODY_ATTRIBUTE: {"S": item.model_dump_json()},
    }
    version = getattr(item, VERSION_ATTRIBUTE, None)
    if isinstance(version, int) and not isinstance(version, bool):
        attributes[VERSION_ATTRIBUTE] = {"N": str(version)}
    return attributes


def decode(attributes: dict[str, AttributeValueTypeDef]) -> object:
    """Rebuild the record, validating from JSON so an ``int`` stays an ``int``."""
    tag = attributes[TYPE_ATTRIBUTE].get("S")
    body = attributes[BODY_ATTRIBUTE].get("S")
    if tag is None or body is None:
        raise TypeTagRefused("stored item is missing its type tag or its body")
    return _resolve(tag).model_validate_json(body)


class DynamoStateStore:
    """``StateStore`` over one DynamoDB table.

    The client is injected rather than built here so that a test, a local
    DynamoDB and a deployed Lambda differ by a constructor argument and by
    nothing else. Selecting between this and ``MemoryStore`` is the composition
    root's job; branching on the environment inside a use case is the thing the
    port exists to prevent.
    """

    def __init__(self, *, client: DynamoDBClient, table_name: str) -> None:
        self._client = client
        self._table = table_name

    # -- reads -------------------------------------------------------------

    def get(self, key: Key) -> object | None:
        """Read one record, strongly consistent.

        Consistency is not tunable here. The callers read a record, decide, and
        then write back under ``VERSION_MUST_BE``; served a stale read, that
        compare-and-set would be computed against a version that no longer
        exists and the retry loop would spin on a conflict it created itself.
        """
        response = self._client.get_item(
            TableName=self._table, Key=self._key(key), ConsistentRead=True
        )
        attributes = response.get("Item")
        if not attributes:
            return None
        return decode(dict(attributes))

    def keys_matching(self, prefix: str) -> list[Key]:
        """Every key whose partition begins with ``prefix``, sorted.

        A ``Scan`` with a ``begins_with`` filter, not a ``Query``. The spec
        suggests querying when the prefix is a whole partition, but the adapter
        cannot tell a whole partition from a prefix of several: with both
        ``PURCHASE#1`` and ``PURCHASE#12`` present, ``Query`` on ``PURCHASE#1``
        returns one partition where the port promises both. A cheaper answer to
        a different question is not an optimisation. Acceptable because the only
        production caller is the operator's effect count (O-3) -- bounded, and
        on no shopper-facing path.
        """
        request = self._scan_request(prefix)
        request["ExpressionAttributeNames"][f"#{SORT_ATTRIBUTE}"] = SORT_ATTRIBUTE
        request["ProjectionExpression"] = f"#{PARTITION_ATTRIBUTE}, #{SORT_ATTRIBUTE}"
        keys: list[Key] = []
        for page in self._scan_pages(request):
            for attributes in page.get("Items", []):
                keys.append((attributes[PARTITION_ATTRIBUTE]["S"], attributes[SORT_ATTRIBUTE]["S"]))
        return sorted(keys)

    def count_matching(self, prefix: str) -> int:
        """The same scan asking only for the number.

        ``Select=COUNT`` so the pages carry counts rather than bodies: a caller
        that wants a number should not pay to deserialise every record to get it.
        """
        request = self._scan_request(prefix)
        request["Select"] = "COUNT"
        return sum(page.get("Count", 0) for page in self._scan_pages(request))

    # -- writes ------------------------------------------------------------

    def transact(self, writes: list[Write]) -> None | ConditionFailed:
        """Commit every write or none of them; return a lost race, never raise it."""
        if not writes:
            return None
        reject_duplicate_keys(writes)
        if len(writes) > TRANSACTION_LIMIT:
            raise ValueError(
                f"{len(writes)} writes exceeds DynamoDB's limit of {TRANSACTION_LIMIT}; "
                "splitting them would give up the all-or-none guarantee"
            )
        try:
            self._client.transact_write_items(
                TransactItems=[self._transact_item(write) for write in writes]
            )
        except ClientError as error:
            failure = self._as_condition_failure(error, writes)
            if failure is None:
                raise
            return failure
        return None

    # -- internals ---------------------------------------------------------

    def _key(self, key: Key) -> dict[str, AttributeValueTypeDef]:
        partition, sort = key
        return {PARTITION_ATTRIBUTE: {"S": partition}, SORT_ATTRIBUTE: {"S": sort}}

    def _transact_item(self, write: Write) -> TransactWriteItemTypeDef:
        guard = _guard_for(write)
        if write.item is None:
            delete: DeleteTypeDef = {"TableName": self._table, "Key": self._key(write.key)}
            guard.apply(delete)
            return {"Delete": delete}
        put: PutTypeDef = {
            "TableName": self._table,
            "Item": self._key(write.key) | encode(write.item),
        }
        guard.apply(put)
        return {"Put": put}

    def _as_condition_failure(
        self, error: ClientError, writes: list[Write]
    ) -> ConditionFailed | None:
        """Turn a guard rejection into a value; leave everything else an error.

        Only a rejected guard becomes ``ConditionFailed``. A throttle, a
        transaction conflict or a size limit is cancelled too, and reporting one
        of those as "someone else approved first" would tell a shopper a
        confident lie about a request that simply never ran.
        """
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code == "ConditionalCheckFailedException" and len(writes) == 1:
            return ConditionFailed(key=writes[0].key, reason=writes[0].reason)
        if code != "TransactionCanceledException":
            return None
        reasons: list[Any] = list(error.response.get("CancellationReasons") or [])
        if not reasons:
            # A service that cancelled without saying why. Work out which guard
            # would have rejected rather than raise through a caller with no
            # ``except`` -- property 1 holds even when the reasons do not arrive.
            return self._recheck(writes)
        for write, reason in zip(writes, reasons, strict=False):
            if str(reason.get("Code", "")) == "ConditionalCheckFailed":
                return ConditionFailed(key=write.key, reason=write.reason)
        return None

    def _recheck(self, writes: list[Write]) -> ConditionFailed | None:
        for write in writes:
            if write.condition is Condition.NONE:
                continue
            existing = self.get(write.key)
            if write.condition is Condition.MUST_NOT_EXIST and existing is not None:
                return ConditionFailed(key=write.key, reason=write.reason)
            if write.condition is Condition.VERSION_MUST_BE and (
                existing is None
                or getattr(existing, VERSION_ATTRIBUTE, None) != write.expected_version
            ):
                return ConditionFailed(key=write.key, reason=write.reason)
        return None

    def _scan_request(self, prefix: str) -> dict[str, Any]:
        return {
            "TableName": self._table,
            "FilterExpression": f"begins_with(#{PARTITION_ATTRIBUTE}, :prefix)",
            "ExpressionAttributeNames": {f"#{PARTITION_ATTRIBUTE}": PARTITION_ATTRIBUTE},
            "ExpressionAttributeValues": {":prefix": {"S": prefix}},
            "ConsistentRead": True,
        }

    def _scan_pages(self, request: dict[str, Any]) -> Iterator[Any]:
        """Follow ``LastEvaluatedKey`` to the end.

        A scan that stopped at the first page would under-report silently, and
        an effect count that is quietly low is worse than no count at all.
        """
        while True:
            page = self._client.scan(**request)
            yield page
            last = page.get("LastEvaluatedKey")
            if not last:
                return
            request["ExclusiveStartKey"] = last


@dataclass(frozen=True, slots=True)
class _Guard:
    """One write's condition, in the three parts DynamoDB wants it in.

    A small type rather than a loose dict because a ``Put`` and a ``Delete`` are
    different shapes to the type checker, and threading an untyped dict into
    both is how a misspelled ``ConditionExpression`` becomes an unguarded write
    that nothing catches until it has already overwritten something.
    """

    expression: str | None = None
    names: dict[str, str] = field(default_factory=dict)
    values: dict[str, AttributeValueTypeDef] = field(default_factory=dict)

    def apply(self, request: PutTypeDef | DeleteTypeDef) -> None:
        if self.expression is None:
            return
        request["ConditionExpression"] = self.expression
        request["ExpressionAttributeNames"] = self.names
        if self.values:
            request["ExpressionAttributeValues"] = self.values


def _guard_for(write: Write) -> _Guard:
    """The guard, as DynamoDB spells it.

    ``VERSION_MUST_BE`` with no expected version is not a no-op: the reference
    implementation compares ``getattr(existing, "version", None)`` against
    ``None``, which holds only for a record that exists and carries no version.
    Spelled out here so the two stores agree on the edge rather than on the
    common case alone.
    """
    if write.condition is Condition.NONE:
        return _Guard()
    names = {f"#{PARTITION_ATTRIBUTE}": PARTITION_ATTRIBUTE}
    if write.condition is Condition.MUST_NOT_EXIST:
        return _Guard(f"attribute_not_exists(#{PARTITION_ATTRIBUTE})", names)
    names[f"#{VERSION_ATTRIBUTE}"] = VERSION_ATTRIBUTE
    if write.expected_version is None:
        return _Guard(
            f"attribute_exists(#{PARTITION_ATTRIBUTE}) AND "
            f"attribute_not_exists(#{VERSION_ATTRIBUTE})",
            names,
        )
    return _Guard(
        f"attribute_exists(#{PARTITION_ATTRIBUTE}) AND #{VERSION_ATTRIBUTE} = :expected",
        names,
        {":expected": {"N": str(write.expected_version)}},
    )


__all__ = [
    "BODY_ATTRIBUTE",
    "PARTITION_ATTRIBUTE",
    "SORT_ATTRIBUTE",
    "TRANSACTION_LIMIT",
    "TYPE_ATTRIBUTE",
    "VERSION_ATTRIBUTE",
    "DynamoStateStore",
    "TypeTagRefused",
    "decode",
    "encode",
    "type_tag",
]
