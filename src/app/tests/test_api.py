"""API contract tests: theme creation, run triggering, artifacts."""

from __future__ import annotations


def test_theme_create_rejects_factor_weights(client) -> None:
    payload = {
        "name": "AI infrastructure",
        "definition": "Chips, networking, and data-center buildout.",
        "sub_exposures": ["ai_infrastructure", "cloud_computing", "data_centers"],
        "factor_weights": {"thematic_z": 1.0},
    }
    response = client.post("/themes", json=payload)
    assert response.status_code == 422


def test_theme_create_and_trigger_run_end_to_end(client) -> None:
    payload = {
        "name": "Grid modernization",
        "definition": "Electrification of transmission, smart grid, storage.",
        "sub_exposures": [
            "transmission_equipment",
            "smart_grid",
            "battery_storage",
            "utilities",
            "infrastructure",
        ],
    }
    created = client.post("/themes", json=payload)
    assert created.status_code == 201, created.text
    theme = created.json()
    assert "factor_weights" in theme["config"]
    assert abs(sum(theme["config"]["factor_weights"].values()) - 1.0) < 1e-9

    triggered = client.post(f"/themes/{theme['theme_id']}/runs")
    assert triggered.status_code == 202, triggered.text
    run_id = triggered.json()["run_id"]

    status = client.get(f"/runs/{run_id}")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] in {"queued", "running", "complete", "failed"}

    if body["status"] == "complete":
        basket = client.get(f"/runs/{run_id}/basket")
        assert basket.status_code == 200
        holdings = basket.json()
        assert 5 <= len(holdings) <= 10
        assert all("composite_score" in h for h in holdings)
        rankings = client.get(f"/runs/{run_id}/rankings")
        assert rankings.status_code == 200
        report = client.get(f"/runs/{run_id}/report")
        assert report.status_code == 200
        assert "investment advice" in report.json()["report_md"].lower()


def test_unknown_sub_exposure_rejected(client) -> None:
    payload = {
        "name": "Bad theme",
        "definition": "unknown mapping",
        "sub_exposures": ["not_mapped", "also_not_mapped", "third_missing"],
    }
    response = client.post("/themes", json=payload)
    assert response.status_code == 422


def test_basket_returns_empty_for_complete_run_without_holdings(client, monkeypatch) -> None:
    async def fake_get_run(run_id: str) -> dict[str, object]:
        return {
            "run_id": run_id,
            "theme_id": "t1",
            "status": "complete",
            "requested_at": "now",
            "retry_count": 0,
            "error_detail": None,
        }

    async def fake_get_basket(run_id: str) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr("app.api.runs.get_run", fake_get_run)
    monkeypatch.setattr("app.api.runs.get_basket_with_scores", fake_get_basket)

    response = client.get("/runs/fake/basket")

    assert response.status_code == 200
    assert response.json() == []


def test_basket_returns_404_before_run_is_complete(client, monkeypatch) -> None:
    async def fake_get_run(run_id: str) -> dict[str, object]:
        return {
            "run_id": run_id,
            "theme_id": "t1",
            "status": "running",
            "requested_at": "now",
            "retry_count": 0,
            "error_detail": None,
        }

    async def fake_get_basket(run_id: str) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr("app.api.runs.get_run", fake_get_run)
    monkeypatch.setattr("app.api.runs.get_basket_with_scores", fake_get_basket)

    response = client.get("/runs/fake/basket")

    assert response.status_code == 404
    assert response.json() == {"detail": "basket not ready"}
