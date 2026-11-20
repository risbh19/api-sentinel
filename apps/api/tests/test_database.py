import pytest

from api_sentinel.database import open_engine


def test_settings_require_an_explicit_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PGDATABASE", raising=False)
    with pytest.raises(ValueError, match="PGDATABASE"):
        open_engine()


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_invalid_port_fails_before_connecting(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    for key in ("PGHOST", "PGUSER", "PGDATABASE"):
        monkeypatch.setenv(key, "synthetic")
    monkeypatch.setenv("PGPORT", port)
    with pytest.raises(ValueError, match="PGPORT"):
        open_engine()
