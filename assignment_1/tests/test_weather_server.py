from __future__ import annotations

import pytest

from mcp_servers import weather_server


@pytest.mark.asyncio
async def test_weather_tool_validates_arguments() -> None:
    with pytest.raises(ValueError, match="between 1 and 7"):
        await weather_server.get_weather("Los Angeles", 8)


@pytest.mark.asyncio
async def test_weather_tool_shapes_provider_data(monkeypatch) -> None:
    responses = iter(
        [
            {
                "results": [
                    {
                        "name": "Los Angeles",
                        "admin1": "California",
                        "country": "United States",
                        "latitude": 34.05,
                        "longitude": -118.24,
                    }
                ]
            },
            {
                "current": {"temperature_2m": 72},
                "current_units": {"temperature_2m": "°F"},
                "daily": {"time": ["2026-10-13"]},
                "daily_units": {},
            },
        ]
    )

    async def fake_get_json(url, params):
        return next(responses)

    monkeypatch.setattr(weather_server, "_get_json", fake_get_json)
    result = await weather_server.get_weather("Los Angeles", 1)

    assert result["location"]["name"] == "Los Angeles"
    assert result["current"]["temperature_2m"] == 72
    assert result["source"] == "Open-Meteo"
