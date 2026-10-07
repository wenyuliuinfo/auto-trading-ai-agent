"""SEC EDGAR filing-type fallback tests."""

from __future__ import annotations

from types import SimpleNamespace

from app.integrations.sec_edgar import get_business_description


def test_get_business_description_falls_back_to_20f(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.integrations.sec_edgar.get_settings",
        lambda: SimpleNamespace(stub_agents=False),
    )

    calls: list[list[str]] = []

    def fake_fetch(ticker: str, form_types: list[str]) -> dict[str, object]:
        calls.append(form_types)
        if form_types == ["10-K", "10-Q"]:
            raise RuntimeError("no ['10-K', '10-Q'] filing found for STM")
        return {
            "item_1_text": "STMicroelectronics designs and manufactures semiconductors.",
            "segment_revenue": None,
            "form": "20-F",
        }

    monkeypatch.setattr(
        "app.integrations.sec_edgar.fetch_sec_edgar_filing", fake_fetch
    )

    result = get_business_description("STM")

    assert calls == [["10-K", "10-Q"], ["20-F"]]
    assert result["form"] == "20-F"
    assert "STMicroelectronics" in result["business_description"]


def test_get_business_description_returns_null_when_all_forms_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.integrations.sec_edgar.get_settings",
        lambda: SimpleNamespace(stub_agents=False),
    )

    def fake_fetch(ticker: str, form_types: list[str]) -> dict[str, object]:
        raise RuntimeError(f"no {form_types} filing found for {ticker}")

    monkeypatch.setattr(
        "app.integrations.sec_edgar.fetch_sec_edgar_filing", fake_fetch
    )

    result = get_business_description("STM")

    assert result["business_description"] is None
    assert result["form"] is None
