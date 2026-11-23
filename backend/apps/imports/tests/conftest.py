import pytest

from .nethelpers import FakeDNS, install_dns


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch) -> FakeDNS:
    """Imports tests never hit the real DNS."""
    return install_dns(monkeypatch)
