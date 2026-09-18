from dataclasses import dataclass
import time
from typing import Any

import httpx
import jwt

from app.core.config import settings


@dataclass(frozen=True)
class QWeatherApi:
    method: str
    path: str
    description: str


QWEATHER_APIS: dict[str, QWeatherApi] = {
    "geo_city_lookup": QWeatherApi(
        method="GET",
        path="/geo/v2/city/lookup",
        description="GeoAPI 城市搜索，用城市名查询 LocationID 和经纬度。",
    ),
    "weather_current": QWeatherApi(
        method="GET",
        path="/weather/v1/current/{latitude}/{longitude}",
        description="实时天气 v1，按经纬度查询当前天气。",
    ),
    "weather_daily": QWeatherApi(
        method="GET",
        path="/weather/v1/daily/{latitude}/{longitude}",
        description="每日天气预报 v1，按经纬度查询未来 1-10 天天气。",
    ),
    "weather_hourly": QWeatherApi(
        method="GET",
        path="/weather/v1/hourly/{latitude}/{longitude}",
        description="小时天气预报 v1，按经纬度查询未来 1-240 小时天气。",
    ),
    "legacy_city_weather_now": QWeatherApi(
        method="GET",
        path="/v7/weather/now",
        description="旧版 WebAPI v7 城市实时天气，按 LocationID 或经纬度查询。",
    ),
}


class QWeatherError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"QWeather error {code}: {message}")
        self.code = code
        self.message = message


def create_qweather_jwt(
    *,
    private_key: str,
    developer_id: str,
    project_id: str,
    credential_id: str,
    expires_in_seconds: int = 900,
    issued_at: int | None = None,
) -> str:
    """Create a QWeather JWT signed with an Ed25519 private key."""
    now = int(issued_at if issued_at is not None else time.time())
    normalized_private_key = private_key.strip().strip('"').replace("\\n", "\n")
    return jwt.encode(
        {
            "sub": project_id.strip(),
            "iat": now - 30,
            "exp": now + expires_in_seconds,
            "iss": developer_id.strip(),
        },
        normalized_private_key,
        algorithm="EdDSA",
        headers={"kid": credential_id.strip()},
    )


def configured_qweather_jwt() -> str | None:
    if settings.qweather_jwt:
        return settings.qweather_jwt.strip()

    if not (
        settings.qweather_private_key
        and settings.qweather_developer_id
        and settings.qweather_project_id
        and settings.qweather_credential_id
    ):
        return None

    return create_qweather_jwt(
        private_key=settings.qweather_private_key,
        developer_id=settings.qweather_developer_id,
        project_id=settings.qweather_project_id,
        credential_id=settings.qweather_credential_id,
    )


def _auth_headers(
    *,
    api_key: str | None = None,
    jwt: str | None = None,
) -> dict[str, str]:
    token = jwt.strip() if jwt else None
    if token:
        return {"Authorization": f"Bearer {token}"}

    key = api_key.strip() if api_key else None
    if key:
        return {"X-QW-Api-Key": key}

    token = configured_qweather_jwt()
    if token:
        return {"Authorization": f"Bearer {token}"}

    key = settings.qweather_api_key.strip() if settings.qweather_api_key else None
    if key:
        return {"X-QW-Api-Key": key}

    raise QWeatherError(
        "MissingApiKey",
        "QWEATHER_API_KEY, QWEATHER_JWT, or QWeather JWT signing config is not set",
    )


def _api_url(path: str, api_host: str | None = None) -> str:
    host = (api_host or settings.qweather_api_host).strip().rstrip("/，, ")
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return f"{host}/{path.lstrip('/')}"


def _api_path(api_name: str, path_params: dict[str, Any] | None = None) -> str:
    api = QWEATHER_APIS.get(api_name)
    if not api:
        raise QWeatherError("UnknownApi", f"Unknown QWeather API: {api_name}")

    try:
        return api.path.format(**(path_params or {}))
    except KeyError as exc:
        raise QWeatherError("MissingPathParam", f"Missing path parameter: {exc}") from exc


def _check_response(data: dict[str, Any]) -> None:
    code = str(data.get("code", ""))
    if code and code != "200":
        raise QWeatherError(code, str(data.get("message") or "QWeather request failed"))


async def request_qweather_api(
    api_name: str,
    *,
    path_params: dict[str, Any] | None = None,
    query_params: dict[str, Any] | None = None,
    api_key: str | None = None,
    jwt: str | None = None,
    api_host: str | None = None,
) -> dict[str, Any]:
    """Call a registered QWeather API and return raw JSON data."""
    api = QWEATHER_APIS.get(api_name)
    if not api:
        raise QWeatherError("UnknownApi", f"Unknown QWeather API: {api_name}")

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.request(
            api.method,
            _api_url(_api_path(api_name, path_params), api_host),
            params=query_params or {},
            headers=_auth_headers(api_key=api_key, jwt=jwt),
        )
    response.raise_for_status()
    data = response.json()
    _check_response(data)
    return data


def _coordinates_from_text(location: str) -> tuple[str, str] | None:
    if "," not in location:
        return None

    longitude, latitude = [part.strip() for part in location.split(",", 1)]
    float(longitude)
    float(latitude)
    return latitude, longitude


async def lookup_qweather_location(
    location: str,
    *,
    api_key: str | None = None,
    jwt: str | None = None,
    api_host: str | None = None,
    lang: str = "zh",
) -> dict[str, Any]:
    """Resolve a city name/address to the first QWeather GeoAPI location object."""
    data = await request_qweather_api(
        "geo_city_lookup",
        query_params={"location": location, "lang": lang},
        api_key=api_key,
        jwt=jwt,
        api_host=api_host,
    )
    locations = data.get("location") or []
    if not locations:
        raise QWeatherError("LocationNotFound", f"No QWeather location found for {location}")
    return dict(locations[0])


async def lookup_qweather_location_id(
    location: str,
    *,
    api_key: str | None = None,
    jwt: str | None = None,
    api_host: str | None = None,
    lang: str = "zh",
) -> str:
    """Resolve a city name/address to a QWeather LocationID."""
    geo = await lookup_qweather_location(
        location,
        api_key=api_key,
        jwt=jwt,
        api_host=api_host,
        lang=lang,
    )
    return str(geo["id"])


async def resolve_qweather_coordinates(
    location: str,
    *,
    api_key: str | None = None,
    jwt: str | None = None,
    api_host: str | None = None,
    lang: str = "zh",
) -> tuple[str, str]:
    """Return latitude and longitude for a city name or 'longitude,latitude' string."""
    coordinates = _coordinates_from_text(location)
    if coordinates:
        return coordinates

    geo = await lookup_qweather_location(
        location,
        api_key=api_key,
        jwt=jwt,
        api_host=api_host,
        lang=lang,
    )
    return str(geo["lat"]), str(geo["lon"])


async def get_qweather_current(
    location: str,
    *,
    api_key: str | None = None,
    jwt: str | None = None,
    api_host: str | None = None,
    lang: str = "zh",
    local_time: bool = True,
) -> dict[str, Any]:
    """Fetch current weather from QWeather v1."""
    latitude, longitude = await resolve_qweather_coordinates(
        location,
        api_key=api_key,
        jwt=jwt,
        api_host=api_host,
        lang=lang,
    )
    return await request_qweather_api(
        "weather_current",
        path_params={"latitude": latitude, "longitude": longitude},
        query_params={"lang": lang, "localTime": str(local_time).lower()},
        api_key=api_key,
        jwt=jwt,
        api_host=api_host,
    )


async def get_qweather_daily(
    location: str,
    *,
    days: int = 7,
    api_key: str | None = None,
    jwt: str | None = None,
    api_host: str | None = None,
    lang: str = "zh",
    local_time: bool = True,
) -> dict[str, Any]:
    """Fetch daily weather forecast from QWeather v1."""
    latitude, longitude = await resolve_qweather_coordinates(
        location,
        api_key=api_key,
        jwt=jwt,
        api_host=api_host,
        lang=lang,
    )
    return await request_qweather_api(
        "weather_daily",
        path_params={"latitude": latitude, "longitude": longitude},
        query_params={
            "days": max(1, min(days, 10)),
            "lang": lang,
            "localTime": str(local_time).lower(),
        },
        api_key=api_key,
        jwt=jwt,
        api_host=api_host,
    )


async def get_qweather_hourly(
    location: str,
    *,
    hours: int = 24,
    api_key: str | None = None,
    jwt: str | None = None,
    api_host: str | None = None,
    lang: str = "zh",
    local_time: bool = True,
) -> dict[str, Any]:
    """Fetch hourly weather forecast from QWeather v1."""
    latitude, longitude = await resolve_qweather_coordinates(
        location,
        api_key=api_key,
        jwt=jwt,
        api_host=api_host,
        lang=lang,
    )
    return await request_qweather_api(
        "weather_hourly",
        path_params={"latitude": latitude, "longitude": longitude},
        query_params={
            "hours": max(1, min(hours, 240)),
            "lang": lang,
            "localTime": str(local_time).lower(),
        },
        api_key=api_key,
        jwt=jwt,
        api_host=api_host,
    )


async def get_qweather_now(
    location: str,
    *,
    api_key: str | None = None,
    jwt: str | None = None,
    api_host: str | None = None,
    lang: str = "zh",
    unit: str = "m",
) -> dict[str, Any]:
    """Fetch legacy WebAPI v7 city current weather data."""
    location_id = (
        location
        if location.isdigit() or "," in location
        else await lookup_qweather_location_id(
            location,
            api_key=api_key,
            jwt=jwt,
            api_host=api_host,
            lang=lang,
        )
    )
    return await request_qweather_api(
        "legacy_city_weather_now",
        query_params={"location": location_id, "lang": lang, "unit": unit},
        api_key=api_key,
        jwt=jwt,
        api_host=api_host,
    )


def _value_text(value: Any, unit: str = "") -> str:
    if value is None:
        return "未知"
    return f"{value}{unit}"


def format_qweather_current(location: str, data: dict[str, Any]) -> str:
    condition = data.get("condition") or {}
    temperature = data.get("temperature") or {}
    feels_like = data.get("feelsLike") or {}
    wind = data.get("wind") or {}
    precipitation = data.get("precipitation") or {}
    pressure = data.get("pressure") or {}
    humidity = data.get("humidity")
    humidity_text = f"{round(float(humidity) * 100)}%" if humidity is not None else "未知"
    wind_direction = (wind.get("direction") or {}).get("compass") or "未知风向"
    wind_speed = wind.get("speed") or {}
    parts = [
        f"{location}当前天气：{condition.get('text', '未知')}",
        f"温度 {_value_text(temperature.get('value'), temperature.get('unit', ''))}",
        f"体感 {_value_text(feels_like.get('value'), feels_like.get('unit', ''))}",
        f"湿度 {humidity_text}",
        f"{wind_direction}，风力 {wind.get('scale', '未知')}级",
        f"风速 {_value_text(wind_speed.get('value'), wind_speed.get('unit', ''))}",
    ]
    amount = precipitation.get("amount") or {}
    if amount.get("value") is not None:
        parts.append(f"降水量 {_value_text(amount.get('value'), amount.get('unit', ''))}")
    if pressure.get("value") is not None:
        parts.append(f"气压 {_value_text(pressure.get('value'), pressure.get('unit', ''))}")
    return "，".join(parts)


def format_qweather_now(location: str, data: dict[str, Any]) -> str:
    now = data.get("now") or {}
    parts = [
        f"{location}当前天气：{now.get('text', '未知')}",
        f"温度 {now.get('temp', '未知')}°C",
        f"体感 {now.get('feelsLike', '未知')}°C",
        f"湿度 {now.get('humidity', '未知')}%",
        f"{now.get('windDir', '未知风向')} {now.get('windScale', '未知')}级",
    ]
    if now.get("precip"):
        parts.append(f"降水量 {now['precip']}mm")
    if data.get("updateTime"):
        parts.append(f"更新时间 {data['updateTime']}")
    return "，".join(parts)


def format_qweather_daily(location: str, data: dict[str, Any]) -> str:
    daily_items = (
        data.get("days")
        or data.get("daily")
        or data.get("forecastDaily", {}).get("weather")
        or []
    )
    if not daily_items:
        return f"{location}未来天气预报：暂无可用数据"

    parts = []
    for item in daily_items[:10]:
        daytime = item.get("daytime") or {}
        condition = daytime.get("condition") or {}
        temp_min_obj = item.get("temperatureMin") or {}
        temp_max_obj = item.get("temperatureMax") or {}
        wind = daytime.get("wind") or {}
        wind_direction = wind.get("direction") or {}
        date = (
            item.get("fxDate")
            or item.get("date")
            or str(item.get("forecastStartTime") or "")[:10]
            or "未知日期"
        )
        text_day = (
            item.get("textDay")
            or item.get("conditionDay")
            or item.get("condition")
            or condition.get("text")
            or "未知"
        )
        temp_min = item.get("tempMin") or item.get("minTemp") or temp_min_obj.get("value")
        temp_max = item.get("tempMax") or item.get("maxTemp") or temp_max_obj.get("value")
        temp_unit = temp_max_obj.get("unit") or temp_min_obj.get("unit") or "°C"
        temp_text = (
            f"{temp_min}-{temp_max}{temp_unit}"
            if temp_min is not None and temp_max is not None
            else "温度未知"
        )
        wind_text = (
            item.get("windDirDay")
            or item.get("windDir")
            or wind_direction.get("compass")
            or ""
        )
        parts.append(f"{date} {text_day} {temp_text}{f' {wind_text}' if wind_text else ''}")
    return f"{location}未来天气预报：" + "；".join(parts)


def format_qweather_hourly(location: str, data: dict[str, Any]) -> str:
    hourly_items = (
        data.get("hours")
        or data.get("hourly")
        or data.get("forecastHourly", {}).get("weather")
        or []
    )
    if not hourly_items:
        return f"{location}小时天气预报：暂无可用数据"

    parts = []
    for item in hourly_items[:12]:
        condition_obj = item.get("condition") or {}
        temp_obj = item.get("temperature") or {}
        wind = item.get("wind") or {}
        wind_direction = wind.get("direction") or {}
        time_text = item.get("fxTime") or item.get("time") or item.get("forecastTime") or "未知时间"
        condition = item.get("text") or condition_obj.get("text") or "未知"
        temp = item.get("temp") or temp_obj.get("value")
        temp_unit = temp_obj.get("unit") or "°C"
        wind_text = item.get("windDir") or item.get("windDirection") or wind_direction.get("compass") or ""
        parts.append(
            f"{time_text} {condition} "
            f"{f'{temp}{temp_unit}' if temp is not None else '温度未知'}"
            f"{f' {wind_text}' if wind_text else ''}"
        )
    return f"{location}小时天气预报：" + "；".join(parts)


async def query_qweather_current(location: str) -> str:
    """Role-agent tool: query current weather and return a concise Chinese summary."""
    data = await get_qweather_current(location)
    return format_qweather_current(location, data)


async def query_qweather_daily(location: str, days: int = 7) -> str:
    """Role-agent tool: query daily forecast and return a concise Chinese summary."""
    data = await get_qweather_daily(location, days=days)
    return format_qweather_daily(location, data)


async def query_qweather_hourly(location: str, hours: int = 24) -> str:
    """Role-agent tool: query hourly forecast and return a concise Chinese summary."""
    data = await get_qweather_hourly(location, hours=hours)
    return format_qweather_hourly(location, data)


async def query_qweather_now(location: str) -> str:
    """Role-agent tool: query legacy city current weather and return a concise Chinese summary."""
    data = await get_qweather_now(location)
    return format_qweather_now(location, data)


async def query_qweather(
    location: str,
    intent: str = "current",
    days: int = 7,
    hours: int = 24,
) -> str:
    """Role-agent tool: unified QWeather query entrypoint."""
    normalized_intent = str(intent or "current").strip().lower()
    if normalized_intent in {"daily", "forecast", "future", "week"}:
        return await query_qweather_daily(location, days=days)
    if normalized_intent in {"hourly", "hours", "next_hours"}:
        return await query_qweather_hourly(location, hours=hours)
    if normalized_intent in {"legacy_now", "now_v7"}:
        return await query_qweather_now(location)
    return await query_qweather_current(location)
