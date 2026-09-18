import asyncio
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx
import jwt

from app.agent.tools.registry import tool_schemas
from app.agent.tools import weather


def test_create_qweather_jwt_signs_with_ed25519_private_key() -> None:
    private_key = Ed25519PrivateKey.generate()
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    token = weather.create_qweather_jwt(
        private_key=private_key_pem,
        developer_id="developer-id",
        project_id="project-id",
        credential_id="credential-id",
        issued_at=1_800_000_000,
    )

    assert jwt.get_unverified_header(token) == {
        "alg": "EdDSA",
        "kid": "credential-id",
        "typ": "JWT",
    }
    assert jwt.decode(
        token,
        private_key.public_key(),
        algorithms=["EdDSA"],
        issuer="developer-id",
        options={"verify_exp": False, "verify_iat": False},
    ) == {
        "sub": "project-id",
        "iat": 1_799_999_970,
        "exp": 1_800_000_900,
        "iss": "developer-id",
    }


def test_get_qweather_now_resolves_city_name(monkeypatch) -> None:
    original_async_client = httpx.AsyncClient
    requested_urls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        assert request.headers["x-qw-api-key"] == "test-key"
        if request.url.path == "/geo/v2/city/lookup":
            assert request.url.params["location"] == "北京"
            return httpx.Response(
                200,
                json={
                    "code": "200",
                    "location": [{"id": "101010100", "lat": "39.90", "lon": "116.40"}],
                },
            )
        if request.url.path == "/v7/weather/now":
            assert request.url.params["location"] == "101010100"
            return httpx.Response(
                200,
                json={
                    "code": "200",
                    "updateTime": "2026-09-17T10:00+08:00",
                    "now": {
                        "text": "晴",
                        "temp": "25",
                        "feelsLike": "24",
                        "humidity": "40",
                        "windDir": "东北风",
                        "windScale": "2",
                    },
                },
            )
        return httpx.Response(404, json={"code": "404"})

    def client_factory(*args, **kwargs):
        return original_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(weather.httpx, "AsyncClient", client_factory)

    async def run() -> dict:
        return await weather.get_qweather_now(
            "北京",
            api_key="test-key",
            api_host="https://example.com",
        )

    data = asyncio.run(run())

    assert [httpx.URL(url).path for url in requested_urls] == [
        "/geo/v2/city/lookup",
        "/v7/weather/now",
    ]
    assert data["now"]["text"] == "晴"
    assert (
        weather.format_qweather_now("北京", data)
        == "北京当前天气：晴，温度 25°C，体感 24°C，湿度 40%，东北风 2级，更新时间 2026-09-17T10:00+08:00"
    )


def test_get_qweather_now_accepts_location_id(monkeypatch) -> None:
    original_async_client = httpx.AsyncClient
    requested_paths = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        assert request.headers["authorization"] == "Bearer test-jwt"
        assert "key" not in dict(request.url.params)
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "code": "200",
                    "now": {
                        "text": "多云",
                        "temp": "28",
                        "feelsLike": "29",
                        "humidity": "60",
                        "windDir": "南风",
                        "windScale": "3",
                    },
                }
            ).encode(),
        )

    def client_factory(*args, **kwargs):
        return original_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(weather.httpx, "AsyncClient", client_factory)

    async def run() -> dict:
        return await weather.get_qweather_now(
            "101010100",
            jwt="test-jwt",
            api_host="https://example.com",
        )

    data = asyncio.run(run())

    assert requested_paths == ["/v7/weather/now"]
    assert data["now"]["text"] == "多云"


def test_get_qweather_current_uses_registered_v1_api(monkeypatch) -> None:
    original_async_client = httpx.AsyncClient
    requested_paths = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        assert request.headers["x-qw-api-key"] == "test-key"
        if request.url.path == "/geo/v2/city/lookup":
            return httpx.Response(
                200,
                json={
                    "code": "200",
                    "location": [{"id": "101010100", "lat": "39.90", "lon": "116.40"}],
                },
            )
        if request.url.path == "/weather/v1/current/39.90/116.40":
            assert request.url.params["lang"] == "zh"
            assert request.url.params["localTime"] == "true"
            return httpx.Response(
                200,
                json={
                    "condition": {"text": "晴"},
                    "temperature": {"value": 25, "unit": "°C"},
                    "feelsLike": {"value": 24, "unit": "°C"},
                    "humidity": 0.4,
                    "wind": {
                        "direction": {"compass": "东北风"},
                        "scale": "2",
                        "speed": {"value": 8, "unit": "km/h"},
                    },
                    "precipitation": {"amount": {"value": 0, "unit": "mm"}},
                    "pressure": {"value": 1012, "unit": "hPa"},
                },
            )
        return httpx.Response(404, json={"code": "404"})

    def client_factory(*args, **kwargs):
        return original_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(weather.httpx, "AsyncClient", client_factory)

    async def run() -> dict:
        return await weather.get_qweather_current(
            "北京",
            api_key="test-key",
            api_host="https://example.com",
        )

    data = asyncio.run(run())

    assert requested_paths == [
        "/geo/v2/city/lookup",
        "/weather/v1/current/39.90/116.40",
    ]
    assert (
        weather.format_qweather_current("北京", data)
        == "北京当前天气：晴，温度 25°C，体感 24°C，湿度 40%，东北风，风力 2级，风速 8km/h，降水量 0mm，气压 1012hPa"
    )


def test_format_qweather_daily_and_hourly() -> None:
    daily_text = weather.format_qweather_daily(
        "北京",
        {
            "daily": [
                {
                    "fxDate": "2026-09-18",
                    "textDay": "多云",
                    "tempMin": "20",
                    "tempMax": "30",
                    "windDirDay": "南风",
                }
            ]
        },
    )
    hourly_text = weather.format_qweather_hourly(
        "北京",
        {
            "hourly": [
                {
                    "fxTime": "2026-09-17T18:00+08:00",
                    "text": "小雨",
                    "temp": "24",
                    "windDir": "东风",
                }
            ]
        },
    )

    assert daily_text == "北京未来天气预报：2026-09-18 多云 20-30°C 南风"
    assert hourly_text == "北京小时天气预报：2026-09-17T18:00+08:00 小雨 24°C 东风"


def test_format_qweather_v1_daily_and_hourly() -> None:
    daily_text = weather.format_qweather_daily(
        "南京",
        {
            "days": [
                {
                    "forecastStartTime": "2026-09-18T00:00+08:00",
                    "daytime": {
                        "condition": {"text": "小雨"},
                        "wind": {"direction": {"compass": "东北风"}},
                    },
                    "temperatureMin": {"value": 18, "unit": "°C"},
                    "temperatureMax": {"value": 24, "unit": "°C"},
                }
            ]
        },
    )
    hourly_text = weather.format_qweather_hourly(
        "南京",
        {
            "hours": [
                {
                    "forecastTime": "2026-09-17T20:00+08:00",
                    "condition": {"text": "阴"},
                    "temperature": {"value": 21, "unit": "°C"},
                    "wind": {"direction": {"compass": "东风"}},
                }
            ]
        },
    )

    assert daily_text == "南京未来天气预报：2026-09-18 小雨 18-24°C 东北风"
    assert hourly_text == "南京小时天气预报：2026-09-17T20:00+08:00 阴 21°C 东风"


def test_weather_tool_schemas_register_all_public_weather_tools() -> None:
    names = {tool["function"]["name"] for tool in tool_schemas()}

    assert names == {"query_qweather"}


def test_query_qweather_routes_by_intent(monkeypatch) -> None:
    calls = []

    async def fake_current(location):
        calls.append(("current", location))
        return "current result"

    async def fake_daily(location, days=7):
        calls.append(("daily", location, days))
        return "daily result"

    async def fake_hourly(location, hours=24):
        calls.append(("hourly", location, hours))
        return "hourly result"

    async def fake_now(location):
        calls.append(("legacy_now", location))
        return "legacy now result"

    monkeypatch.setattr(weather, "query_qweather_current", fake_current)
    monkeypatch.setattr(weather, "query_qweather_daily", fake_daily)
    monkeypatch.setattr(weather, "query_qweather_hourly", fake_hourly)
    monkeypatch.setattr(weather, "query_qweather_now", fake_now)

    async def run() -> list[str]:
        return [
            await weather.query_qweather("南京", intent="current"),
            await weather.query_qweather("南京", intent="daily", days=3),
            await weather.query_qweather("南京", intent="hourly", hours=12),
            await weather.query_qweather("南京", intent="legacy_now"),
        ]

    assert asyncio.run(run()) == [
        "current result",
        "daily result",
        "hourly result",
        "legacy now result",
    ]
    assert calls == [
        ("current", "南京"),
        ("daily", "南京", 3),
        ("hourly", "南京", 12),
        ("legacy_now", "南京"),
    ]
