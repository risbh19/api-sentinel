import sys

import pytest

from api_sentinel import worker
from api_sentinel.detections.rules import RuleSet


def test_threshold_configuration_defaults_bounds_and_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = [
        "SENTINEL_AUTHENTICATION_FAILURES_THRESHOLD",
        "SENTINEL_AUTHORIZATION_DENIALS_THRESHOLD",
        "SENTINEL_HIGH_REQUEST_VOLUME_THRESHOLD",
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)
    defaults = RuleSet()
    assert RuleSet.from_environment() == defaults
    for name, value in zip(names, ("1", "100", "61"), strict=True):
        monkeypatch.setenv(name, value)
    configured = RuleSet.from_environment()
    assert (configured.failures.threshold, configured.failures.version) == (1, 1001)
    assert (configured.denials.threshold, configured.denials.version) == (100, 1100)
    assert configured.volume == defaults.volume
    monkeypatch.setenv(names[0], "8")
    assert RuleSet.from_environment().failures == defaults.failures


@pytest.mark.parametrize("value", ["", "0", "-1", "101", "1.5", " 8", "８", "invalid-marker"])
def test_invalid_threshold_stops_worker_before_claiming_jobs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    name = "SENTINEL_HIGH_REQUEST_VOLUME_THRESHOLD"
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(sys, "argv", ["worker"])
    with pytest.raises(SystemExit) as exc:
        worker.main()
    assert exc.value.code == 2
    message = capsys.readouterr().err
    assert f"{name} must be an integer between 1 and 100" in message
    assert "invalid-marker" not in message
