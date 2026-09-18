"""The inputs behind the WP-02 golden vectors.

Kept beside the domain so the generator script and the verifying test read the
same cases, and so adding a case is one edit rather than two that can drift.

These are plain JSON-able values on purpose: another implementation -- P4's
simulator, or a reimplementation in another language -- must be able to feed
exactly these inputs in without importing Python models.
"""

from __future__ import annotations

from typing import Any

CASES: dict[str, list[dict[str, Any]]] = {
    "digests": [
        {
            "name": "quote: single line, one known delivery charge",
            "tag": "quote",
            "payload": {
                "owner_id": "owner-0001",
                "purchase_id": "purchase-0001",
                "purchase_version": 1,
                "quote_id": "quote-00000001",
                "quote_version": 1,
                "seller_id": "demo-seller-01",
                "source_merchant_id": "merchant-a",
                "mode": "live",
                "lines": [
                    {
                        "sku": "sku-00001",
                        "name": "Basmati rice 1kg",
                        "quantity_base": 5000,
                        "dimension": "mass",
                        "unit_price_paise": 12000,
                        "line_total_paise": 60000,
                        "substituted": False,
                    }
                ],
                "charges": [{"kind": "delivery", "confidence": "verified", "amount_paise": 2000}],
                "currency": "INR",
                "delivery": "standard",
                "expires_at": "2026-09-15T12:02:00.000Z",
            },
        },
        {
            "name": "quote: identical to the first but in fixture mode",
            "tag": "quote",
            "payload": {
                "owner_id": "owner-0001",
                "purchase_id": "purchase-0001",
                "purchase_version": 1,
                "quote_id": "quote-00000001",
                "quote_version": 1,
                "seller_id": "demo-seller-01",
                "source_merchant_id": "merchant-a",
                "mode": "fixture",
                "lines": [
                    {
                        "sku": "sku-00001",
                        "name": "Basmati rice 1kg",
                        "quantity_base": 5000,
                        "dimension": "mass",
                        "unit_price_paise": 12000,
                        "line_total_paise": 60000,
                        "substituted": False,
                    }
                ],
                "charges": [{"kind": "delivery", "confidence": "verified", "amount_paise": 2000}],
                "currency": "INR",
                "delivery": "standard",
                "expires_at": "2026-09-15T12:02:00.000Z",
            },
        },
        {
            "name": "diff: empty change list",
            "tag": "diff",
            "payload": [],
        },
        {
            "name": "diff: one price change",
            "tag": "diff",
            "payload": [
                {
                    "kind": "price",
                    "target": "sku-00001",
                    "before": "12000",
                    "after": "12500",
                }
            ],
        },
        {
            "name": "lines: two lines, order significant",
            "tag": "lines",
            "payload": [
                {"sku": "sku-00001", "quantity_base": 5000},
                {"sku": "sku-00002", "quantity_base": 2000},
            ],
        },
        {
            "name": "idempotency: approve request",
            "tag": "idempotency",
            "payload": {
                "method": "POST",
                "path_template": "/purchases/{id}/approve",
                "path_params": {"id": "purchase-0001"},
                "owner_id": "owner-0001",
                "body": {
                    "quote_id": "quote-00000001",
                    "quote_hash": "0" * 64,
                    "quote_version": 1,
                    "expected_purchase_version": 1,
                },
            },
        },
        {
            "name": "canonical: explicit null is not an omitted key",
            "tag": "diff",
            "payload": {"delivery_charge": None},
        },
        {
            "name": "canonical: unicode normalises to NFC",
            "tag": "diff",
            "payload": {"name": "café"},
        },
    ],
    "approval_ids": [
        {
            "name": "approval id from a quote",
            "inputs": {
                "quote_id": "quote-00000001",
                "quote_hash": "0" * 64,
                "quote_version": 1,
            },
        }
    ],
    "payment_keys": [
        {
            "name": "payment key for purchase-0001",
            "inputs": {
                "purchase_id": "purchase-0001",
                "approval_id": "approval-000000001",
            },
        }
    ],
    "order_keys": [
        {
            "name": "order key for attempt-0001",
            "inputs": {"purchase_id": "purchase-0001", "attempt_id": "attempt-0001"},
        }
    ],
}
