"""Real, Bedrock-backed extraction (WP-05, P2's slice).

Gated on `services.agent.config.BEDROCK_MODEL_ID`, which WP-01's cloud
checkpoint has not pinned yet -- every environment today has it unset. This
module still imports cleanly with no model configured: the failure happens
per call (`ExtractorUnavailable`), not at import time, so `services/agent`
can start up in fixture-only environments without ever touching `boto3`'s
network path.

Not yet run against a real model -- same "not yet run" honesty note WP-06
gave for live Blinkit/Zepto verification (`docs/specs/
WP-06-search-comparison-basket-repair.md`). Expected to work once
`BEDROCK_MODEL_ID` is set, since it implements the exact `Extractor` port the
fake backend already satisfies and is tested against.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from services.agent.config import AWS_REGION, BEDROCK_MODEL_ID

from .base import Extractor, ExtractorUnavailable
from .models import CandidateItem, ExtractionResult, UnresolvedCandidate

#: services.domain.units.Unit's string values -- kept as a plain tuple here
#: so this module never imports the domain package for a single literal.
_VALID_UNITS = ("g", "kg", "ml", "l", "piece")
_VALID_FLEXIBILITIES = (
    "exact_only",
    "brand_flexible",
    "pack_flexible",
    "brand_and_pack_flexible",
)
_VALID_REASON_CODES = (
    "no_quantity_detected",
    "ambiguous_item",
    "no_items_detected",
)

_MIME_TO_BEDROCK_FORMAT = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/gif": "gif",
    "image/webp": "webp",
}

_SYSTEM_PROMPT = """You extract a shopper's grocery list into strict JSON. \
Never invent a quantity, unit, brand, or attribute the shopper did not state \
-- absence is never assent. Output ONLY a JSON object with this exact shape, \
nothing else, no markdown fences:

{
  "items": [
    {
      "raw_fragment": "<the exact phrase this came from>",
      "name": "<item name, no quantity or unit words>",
      "quantity_value": <number>,
      "unit": "g" | "kg" | "ml" | "l" | "piece",
      "hard_attributes": {"<attribute name>": "<value>"},
      "flexibility": "exact_only" | "brand_flexible" | "pack_flexible" | "brand_and_pack_flexible"
    }
  ],
  "unresolved": [
    {
      "raw_fragment": "<the exact phrase this came from>",
      "reason_code": "no_quantity_detected" | "ambiguous_item" | "no_items_detected",
      "reason_detail": "<short explanation, or null>"
    }
  ]
}

Rules:
- hard_attributes is empty {} unless the shopper explicitly named an
  attribute (e.g. "organic").
- flexibility defaults to "exact_only" unless the shopper explicitly said
  they'd accept a substitute.
- If a fragment names an item with no parsable quantity, put it in
  unresolved with reason_code "no_quantity_detected", never guess a
  quantity.
- If nothing resembling a shopping item is present at all, return empty
  "items" and one "unresolved" entry with reason_code "no_items_detected"."""


def _parse_model_json(raw_text: str) -> ExtractionResult:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ExtractorUnavailable(f"model output was not valid JSON: {exc}") from exc

    try:
        candidates = tuple(
            CandidateItem(
                raw_fragment=str(item["raw_fragment"]),
                name=str(item["name"]),
                quantity_value=float(item["quantity_value"]),
                unit=_require_one_of(str(item["unit"]), _VALID_UNITS, "unit"),
                hard_attributes={
                    str(k): str(v) for k, v in dict(item.get("hard_attributes") or {}).items()
                },
                flexibility=_require_one_of(
                    str(item.get("flexibility", "exact_only")),
                    _VALID_FLEXIBILITIES,
                    "flexibility",
                ),
            )
            for item in parsed.get("items", [])
        )
        unresolved = tuple(
            UnresolvedCandidate(
                raw_fragment=str(entry["raw_fragment"]),
                reason_code=_require_one_of(
                    str(entry["reason_code"]), _VALID_REASON_CODES, "reason_code"
                ),
                reason_detail=(
                    str(entry["reason_detail"]) if entry.get("reason_detail") is not None else None
                ),
            )
            for entry in parsed.get("unresolved", [])
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExtractorUnavailable(
            f"model output did not match the extraction schema: {exc}"
        ) from exc

    return ExtractionResult(candidates=candidates, unresolved=unresolved)


def _require_one_of(value: str, allowed: tuple[str, ...], field_name: str) -> str:
    if value not in allowed:
        raise ValueError(f"{field_name}={value!r} is not one of {allowed}")
    return value


class BedrockExtractor(Extractor):
    """Real backend: one Bedrock `converse` call per request."""

    name = "bedrock"

    def __init__(self) -> None:
        self._client: Any | None = None  # lazy: never touch the network at import time

    def _require_model(self) -> str:
        if not BEDROCK_MODEL_ID:
            raise ExtractorUnavailable(
                "BEDROCK_MODEL_ID is not set; WP-01's cloud checkpoint has not "
                "pinned a real model yet"
            )
        return BEDROCK_MODEL_ID

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3  # local import: keeps `boto3` off the module's import-time cost

            self._client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        return self._client

    def _converse(self, content_blocks: list[dict[str, Any]]) -> ExtractionResult:
        model_id = self._require_model()
        client = self._get_client()
        try:
            response = client.converse(
                modelId=model_id,
                system=[{"text": _SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": content_blocks}],
                inferenceConfig={"temperature": 0.0, "maxTokens": 2048},
            )
        except (ClientError, BotoCoreError) as exc:
            raise ExtractorUnavailable(f"Bedrock call failed: {exc}") from exc

        try:
            raw_text = response["output"]["message"]["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExtractorUnavailable(f"unexpected Bedrock response shape: {exc}") from exc

        return _parse_model_json(raw_text)

    def extract_from_text(self, transcript: str, deadline: datetime) -> ExtractionResult:
        del deadline  # a single converse call; boto3's own client timeout applies
        return self._converse([{"text": transcript}])

    def extract_from_image(
        self, image_bytes: bytes, mime_type: str, deadline: datetime
    ) -> ExtractionResult:
        del deadline
        image_format = _MIME_TO_BEDROCK_FORMAT.get(mime_type)
        if image_format is None:
            raise ExtractorUnavailable(f"unsupported image mime type: {mime_type!r}")
        return self._converse(
            [
                {"image": {"format": image_format, "source": {"bytes": image_bytes}}},
                {"text": "Extract this shopper's grocery list photo per the schema."},
            ]
        )


__all__ = ["BedrockExtractor"]
