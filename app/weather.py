from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, status

from .config import get_settings


@dataclass(frozen=True)
class Weather:
    temperature_c: float
    precipitation_mm: float
    kind: str
    source: str


class WeatherService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def get_daily(self, latitude: float, longitude: float, target: date) -> Weather:
        today = datetime.now(ZoneInfo("America/Bogota")).date()
        if target > today + timedelta(days=16):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Open-Meteo solo ofrece pronóstico operativo hasta 16 días.")
        if target < today - timedelta(days=5):
            base_url = "https://archive-api.open-meteo.com/v1/archive"
            kind = "observed"
        else:
            base_url = "https://api.open-meteo.com/v1/forecast"
            kind = "forecast" if target >= today else "observed"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": target.isoformat(),
            "end_date": target.isoformat(),
            "daily": "temperature_2m_mean,precipitation_sum",
            "timezone": "America/Bogota",
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.weather_timeout_seconds) as client:
                response = await client.get(base_url, params=params)
                response.raise_for_status()
                daily = response.json()["daily"]
                return Weather(
                    temperature_c=float(daily["temperature_2m_mean"][0]),
                    precipitation_mm=float(daily["precipitation_sum"][0]),
                    kind=kind,
                    source=str(response.url),
                )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, IndexError) as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No fue posible obtener datos meteorológicos verificables.") from exc

