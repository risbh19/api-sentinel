from datetime import UTC, datetime, timedelta

from access_helpers import ORIGIN, add_user, login
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from test_detection_rules import drain, project, sample, send
from test_events import make_project

from api_sentinel.detections.rules import AUTH_FAILURES
from api_sentinel.identity.security import Role
from api_sentinel.main import create_app


def test_overview_counts_real_project_data_in_selected_window(database: Engine) -> None:
    owner, _, org = add_user(database)
    target, foreign = make_project(database, org), project(database)
    path = f"/api/v1/projects/{target}"
    stamp = datetime.now(UTC) - timedelta(minutes=1)
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        assert client.get(path + "/metrics/overview").status_code == 401
        headers = login(client, owner)
        assert client.get(path + "/metrics/overview").json()["events"] == 0
        assert client.get(f"/api/v1/projects/{foreign}/metrics/overview").status_code == 404
        for pid in (target, foreign):
            send(database, pid, [sample(AUTH_FAILURES, str(i), stamp) for i in range(8)])
        send(database, target, [sample(AUTH_FAILURES, "older", stamp - timedelta(days=3))])
        drain(database)
        assert (
            client.post(
                path + "/incidents", headers=headers, json={"title": "Fixture"}
            ).status_code
            == 201
        )
        for window, expected in (("24h", 8), ("7d", 9)):
            data = client.get(path + "/metrics/overview", params={"window": window}).json()
            assert data["events"] == sum(b["events"] for b in data["buckets"]) == expected
            assert len(data["buckets"]) == 6 and data["buckets"][-1]["events"] == 8
            assert (data["open_alerts"], data["active_incidents"]) == (1, 1)
        assert client.get(path + "/metrics/overview?window=all").status_code == 422


def test_viewer_can_access_aggregate_counts(database: Engine) -> None:
    email, _, org = add_user(database, Role.VIEWER)
    pid = make_project(database, org)
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        login(client, email)
        assert client.get(f"/api/v1/projects/{pid}/metrics/overview").status_code == 200
