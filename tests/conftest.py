import os
import pytest

@pytest.fixture(scope="session")
def base_url():
    return os.environ.get("TEST_BASE_URL", "https://otdev1602.wpengine.com")

@pytest.fixture(scope="session")
def client_credentials():
    return {
        "email": os.environ["TEST_CLIENT_EMAIL"],
        "password": os.environ["TEST_CLIENT_PASSWORD"],
    }
