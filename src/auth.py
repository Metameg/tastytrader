from dataclasses import dataclass
import httpx

BASE_URL = "https://api.cert.tastyworks.com"


@dataclass
class Auth:
    session_token: str
    remember_token: str


async def login(username: str, password: str, base_url: str = BASE_URL) -> Auth:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/sessions",
            json={"login": username, "password": password},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return Auth(
            session_token=data["session-token"],
            remember_token=data["remember-token"],
        )
