import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from dashboard.app import app
    with TestClient(app) as c:
        yield c


def test_root_returns_200_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_html_links_to_tokens_css(client):
    response = client.get("/")
    assert "/static/css/tokens.css" in response.text


def test_html_links_to_layout_css(client):
    response = client.get("/")
    assert "/static/css/layout.css" in response.text


def test_html_links_to_components_css(client):
    response = client.get("/")
    assert "/static/css/components.css" in response.text


def test_html_has_no_inline_styles(client):
    response = client.get("/")
    assert 'style="' not in response.text


def test_static_tokens_css_served(client):
    response = client.get("/static/css/tokens.css")
    assert response.status_code == 200


def test_static_layout_css_served(client):
    response = client.get("/static/css/layout.css")
    assert response.status_code == 200


def test_static_components_css_served(client):
    response = client.get("/static/css/components.css")
    assert response.status_code == 200


def test_app_has_config_loaded(client):
    from dashboard.app import app
    assert app.state.config is not None
    assert app.state.config.execution.account_number == "5WX78966"
