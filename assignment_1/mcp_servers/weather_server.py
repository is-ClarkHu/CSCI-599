from __future__ import annotations

from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("open-meteo-weather")
HTTP_TIMEOUT = 12.0


async def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Weather provider returned a malformed response")
    return payload


@mcp.tool()
async def get_weather(location: str, forecast_days: int = 3) -> dict[str, Any]:
    """Get current weather and a 1-7 day forecast for a city or named location."""

    location = location.strip()
    if not location:
        raise ValueError("location must not be empty")
    if not 1 <= forecast_days <= 7:
        raise ValueError("forecast_days must be between 1 and 7")

    geocoding = await _get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": location, "count": 1, "language": "en", "format": "json"},
    )
    results = geocoding.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError(f"No location found for {location!r}")

    place = results[0]
    forecast = await _get_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "auto",
            "forecast_days": forecast_days,
        },
    )
    return {
        "location": {
            "name": place.get("name"),
            "admin1": place.get("admin1"),
            "country": place.get("country"),
            "latitude": place.get("latitude"),
            "longitude": place.get("longitude"),
        },
        "current": forecast.get("current"),
        "current_units": forecast.get("current_units"),
        "daily": forecast.get("daily"),
        "daily_units": forecast.get("daily_units"),
        "source": "Open-Meteo",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
