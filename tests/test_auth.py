import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.auth import Auth, login

BASE_URL = "https://api.cert.tastyworks.com"


async def test_login_returns_auth_with_tokens():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "session-token": "tok_session",
            "remember-token": "tok_remember",
        }
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("src.auth.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        auth = await login("user", "pass", base_url=BASE_URL)

    assert auth.session_token == "tok_session"
    assert auth.remember_token == "tok_remember"
    mock_client.post.assert_called_once_with(
        f"{BASE_URL}/sessions",
        json={"login": "user", "password": "pass"},
    )


async def test_login_raises_on_bad_credentials():
    import httpx

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=MagicMock()
    )

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("src.auth.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        with pytest.raises(Exception):
            await login("bad", "creds", base_url=BASE_URL)
