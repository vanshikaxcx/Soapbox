"""FastAPI entrypoint: auth gating and the `/tasks/compare`/`/tasks/extract`
wiring (WP-04/WP-06/WP-05).

Uses `Mode.FIXTURE` throughout -- the disclosed, deterministic demo fallback
-- so these tests never touch a real browser or network call. `/tasks/search`
already had no automated coverage (WP-04's spec: "blocked on WP-00's
pytest/lint config"); that config is merged now, so this closes the gap for
both task endpoints while it's here.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from services.domain.intent import Intent, Item
from services.domain.units import Quantity, Unit

from services.agent import main as main_module
from services.agent.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def an_intent(*, budget_paise: int | None = None) -> dict[str, object]:
    intent = Intent(
        intent_id="intent-00000001",
        owner_id="owner-00000001",
        items=(Item(item_id="item-00000001", name="rice", quantity=Quantity.of(5, Unit.KG)),),
        location="Connaught Place, New Delhi",
        budget_paise=budget_paise,
    )
    return intent.model_dump(mode="json")


LOCATION = {"locality": "Connaught Place", "pincode": "110001"}


def test_health_responds_without_auth(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_tasks_search_returns_fixture_observations(client: TestClient) -> None:
    resp = client.post(
        "/tasks/search",
        json={
            "location": LOCATION,
            "item": {"name": "rice", "quantity": 5, "unit": "kg"},
            "mode": "fixture",
        },
    )
    assert resp.status_code == 200
    observations = resp.json()["observations"]
    assert observations
    assert {o["mode"] for o in observations} == {"fixture"}


def test_tasks_compare_returns_a_provable_winner_in_fixture_mode(client: TestClient) -> None:
    """Fixture fees are labeled "complete" (unlike the live connectors', which
    are always "estimated") -- so unlike a live comparison, a fixture-mode
    comparison between two full-price merchants can produce a definitive
    winner, and this exercises that real path end to end.
    """
    resp = client.post(
        "/tasks/compare",
        json={"intent": an_intent(), "location": LOCATION, "mode": "fixture"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "fixture"
    assert len(body["results"]) == 2
    assert all(r["basket"] is not None for r in body["results"])
    assert body["winner_merchant_id"] in {"blinkit", "zepto"}


def test_tasks_compare_respects_the_intent_budget(client: TestClient) -> None:
    tight = client.post(
        "/tasks/compare",
        json={"intent": an_intent(budget_paise=1), "location": LOCATION, "mode": "fixture"},
    )
    assert tight.json()["winner_merchant_id"] is None
    assert tight.json()["budget_check"] == "exceeded"


def test_tasks_search_requires_the_bearer_token_when_one_is_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_module, "AGENT_SERVICE_TOKEN", "secret-token")
    resp = client.post(
        "/tasks/search",
        json={
            "location": LOCATION,
            "item": {"name": "rice", "quantity": 5, "unit": "kg"},
            "mode": "fixture",
        },
    )
    assert resp.status_code == 401


def test_tasks_compare_requires_the_bearer_token_when_one_is_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_module, "AGENT_SERVICE_TOKEN", "secret-token")
    resp = client.post(
        "/tasks/compare",
        json={"intent": an_intent(), "location": LOCATION, "mode": "fixture"},
    )
    assert resp.status_code == 401


def test_tasks_compare_accepts_the_configured_bearer_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_module, "AGENT_SERVICE_TOKEN", "secret-token")
    resp = client.post(
        "/tasks/compare",
        json={"intent": an_intent(), "location": LOCATION, "mode": "fixture"},
        headers={"Authorization": "Bearer secret-token"},
    )
    assert resp.status_code == 200


def test_tasks_extract_resolves_items_from_a_transcript(client: TestClient) -> None:
    resp = client.post(
        "/tasks/extract",
        json={"transcript": "2 kg rice, 500 ml milk", "mode": "fixture"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [item["name"] for item in body["items"]] == ["rice", "milk"]
    assert body["unresolved"] == []


def test_tasks_extract_rejects_neither_transcript_nor_image(client: TestClient) -> None:
    resp = client.post("/tasks/extract", json={"mode": "fixture"})
    assert resp.status_code == 400


def test_tasks_extract_rejects_both_transcript_and_image(client: TestClient) -> None:
    resp = client.post(
        "/tasks/extract",
        json={
            "transcript": "2 kg rice",
            "image_base64": "aGVsbG8=",
            "image_mime_type": "image/jpeg",
            "mode": "fixture",
        },
    )
    assert resp.status_code == 400


def test_tasks_extract_requires_the_bearer_token_when_one_is_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_module, "AGENT_SERVICE_TOKEN", "secret-token")
    resp = client.post(
        "/tasks/extract",
        json={"transcript": "2 kg rice", "mode": "fixture"},
    )
    assert resp.status_code == 401
