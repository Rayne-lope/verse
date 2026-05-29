from __future__ import annotations

import requests


def get_weather(city: str) -> str:
    """Get the current weather for a given city name using the free Open-Meteo API."""
    if not city.strip():
        return "City name cannot be empty."

    try:
        # 1. Geocoding: Get latitude and longitude of the city
        geocode_url = f"https://geocoding-api.open-meteo.com/v1/search?name={requests.utils.quote(city)}&count=1&language=en&format=json"
        geo_res = requests.get(geocode_url, timeout=10)
        geo_res.raise_for_status()
        geo_data = geo_res.json()

        results = geo_data.get("results", [])
        if not results and len(city.strip().split()) > 1:
            fallback_city = city.strip().split()[0]
            geocode_url = f"https://geocoding-api.open-meteo.com/v1/search?name={requests.utils.quote(fallback_city)}&count=1&language=en&format=json"
            geo_res = requests.get(geocode_url, timeout=10)
            geo_res.raise_for_status()
            geo_data = geo_res.json()
            results = geo_data.get("results", [])

        if not results:
            return f"Could not find coordinates for city: '{city}'."

        location = results[0]
        lat = location["latitude"]
        lon = location["longitude"]
        name = location.get("name", city)
        country = location.get("country", "")

        # 2. Weather: Get current weather using coordinates
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        weather_res = requests.get(weather_url, timeout=10)
        weather_res.raise_for_status()
        weather_data = weather_res.json()

        current = weather_data.get("current_weather", {})
        if not current:
            return f"Weather data not available for '{name}'."

        temp = current.get("temperature", "unknown")
        windspeed = current.get("windspeed", "unknown")
        weathercode = current.get("weathercode", 0)

        # Interpret weather codes (simplified WMO codes)
        wmo_interpretations = {
            0: "Clear sky",
            1: "Mainly clear",
            2: "Partly cloudy",
            3: "Overcast",
            45: "Fog",
            48: "Depositing rime fog",
            51: "Light drizzle",
            53: "Moderate drizzle",
            55: "Dense drizzle",
            61: "Slight rain",
            63: "Moderate rain",
            65: "Heavy rain",
            71: "Slight snow fall",
            73: "Moderate snow fall",
            75: "Heavy snow fall",
            77: "Snow grains",
            80: "Slight rain showers",
            81: "Moderate rain showers",
            82: "Violent rain showers",
            85: "Slight snow showers",
            86: "Heavy snow showers",
            95: "Thunderstorm",
            96: "Thunderstorm with slight hail",
            99: "Thunderstorm with heavy hail",
        }
        condition = wmo_interpretations.get(weathercode, "unknown conditions")

        loc_str = f"{name}, {country}" if country else name
        return f"Current weather in {loc_str}: {temp}°C, {condition}. Wind speed: {windspeed} km/h."
    except Exception as exc:
        return f"Failed to retrieve weather data for '{city}': {exc}"
