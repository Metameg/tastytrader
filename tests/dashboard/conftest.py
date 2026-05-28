import os


def pytest_configure(config):
    os.environ.setdefault("TASTYTRADE_USERNAME", "test_user")
    os.environ.setdefault("TASTYTRADE_PASSWORD", "test_pass")
