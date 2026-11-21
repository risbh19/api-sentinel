from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from access_helpers import ORIGIN, add_user, login
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from test_detection_rules import drain, sample, send
from test_events import make_project

from api_sentinel.database import transaction
from api_sentinel.detections.rules import AUTH_FAILURES
from api_sentinel.identity.models import Membership
from api_sentinel.identity.security import Role
from api_sentinel.incidents.models import Incident, IncidentAlert
from api_sentinel.main import create_app


def test_manual_investigation_timeline_and_retention(database: Engine, config: Config) -> None:
    email, actor, org = add_user(database)
    project = make_project(database, org)
    path = f"/api/v1/projects/{project}/incidents"
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        headers = login(client, email)
        assert client.post(path, json={"title": "Triage"}).status_code == 403
        payload = {"title": "Triage", "priority": "high", "request_key": str(uuid4())}
        made = client.post(path, headers=headers, json=payload)
        replay = client.post(path, headers=headers, json=payload)
        assert replay.status_code == 200 and replay.json() == made.json()
        assert client.post(path, headers=headers, json={**payload, "title": "Changed"}).status_code == 409
        assert made.status_code == 201
        url = path + "/" + made.json()["id"]
        version = made.json()["version"]
        assert client.patch(url, headers=headers, json={"status": "resolved", "version": version}).status_code == 409
        assert client.patch(url, headers=headers, json={"assignee_id": str(uuid4()), "version": version}).status_code == 422
        change = client.patch(url, headers=headers, json={"assignee_id": str(actor), "version": version})
        assert change.status_code == 200
        assert client.post(url + "/notes", headers=headers, json={"text": "stale", "version": version}).status_code == 409
        version = change.json()["version"]
        for status in ("acknowledged", "investigating", "resolved", "reopened", "investigating"):
            response = client.patch(url, headers=headers, json={"status": status, "version": version})
            assert response.status_code == 200
            assert (response.json()["resolved_at"] is not None) == (status == "resolved")
            version = response.json()["version"]
        note = client.post(url + "/notes", headers=headers, json={"text": "Synthetic investigation", "version": version})
        assert note.status_code == 201
        assert client.get(path, params={"status":"resolved"}).json() == []
        assert client.get(path, params={"status":"investigating"}).json()[0]["id"] == made.json()["id"]
        page = client.get(url, params={"limit":2}).json()
        assert page["assignee_id"] == str(actor) and page["next_version"] == 2
        tail = client.get(url, params={"after_version":2}).json()["timeline"]
        assert tail[-1]["note"] == "Synthetic investigation"
        assert [row["version"] for row in page["timeline"] + tail] == list(range(1, version+2))
        assert all(row["actor_id"] == str(actor) for row in tail)
        facts = client.get(f"/api/v1/organizations/{org}/audit?project_id={project}").json()["entries"]
        changes = [entry for entry in facts if entry["action"] == "incident.changed"]
        assert sorted(entry["incident_version"] for entry in changes) == list(range(1, version+2))
        assert all(entry["incident_id"] == made.json()["id"] and entry["request_id"] for entry in changes)
        assert "Synthetic investigation" not in str(changes)
        assert client.delete(f"/api/v1/organizations/{org}/projects/{project}", headers=headers).status_code == 409
    with pytest.raises(RuntimeError, match="discard incident history"):
        command.downgrade(config, "0009_alert_correlation")
    with database.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM incident_activity")) == version + 1


@pytest.mark.parametrize("role", [Role.ANALYST, Role.DEVELOPER, Role.VIEWER])
def test_role_and_project_boundaries(database: Engine, role: Role) -> None:
    owner, _, org = add_user(database)
    email, target, foreign_org = add_user(database, role)
    project, foreign = make_project(database, org), make_project(database, foreign_org)
    path = f"/api/v1/projects/{project}/incidents"
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        headers = login(client, owner)
        made = client.post(path, json={"title":"Sensitive investigation"}, headers=headers).json()
        url = path + "/" + made["id"]
        assignment = {"version":1, "assignee_id":str(target)}
        assert client.patch(url, headers=headers, json=assignment).status_code == 422
        with transaction(database) as db:
            db.add(Membership(organization_id=org, user_id=target, role=role))
        headers = login(client, email)
        assert client.get(f"/api/v1/projects/{foreign}/incidents/{made['id']}").status_code == 404
        detail = client.get(url).json()
        result = client.patch(url, headers=headers, json=assignment)
        if role == Role.ANALYST:
            assert detail["title"] == "Sensitive investigation" and result.status_code == 200
            headers = login(client, owner)
            member_url = f"/api/v1/organizations/{org}/members/{target}"
            assert client.delete(member_url, headers=headers).status_code == 409
            assert client.put(member_url, headers=headers, json={"role":"viewer"}).status_code == 409
            assert client.patch(url, headers=headers, json={"assignee_id":None,"version":2}).status_code == 200
            assert client.delete(member_url, headers=headers).status_code == 204
        else:
            assert result.status_code == 403
            assert {"title","assignee_id","timeline"}.isdisjoint(detail)
            assert client.post(path, json={"title":"Denied"}, headers=headers).status_code == 403
            assert client.post(url+"/notes", json={"text":"Denied","version":1}, headers=headers).status_code == 403


def test_alert_promotion_is_atomic_and_project_scoped(database: Engine) -> None:
    owner, _, org = add_user(database)
    first, second = make_project(database, org), make_project(database, org, "other")
    for project in (first, second):
        send(database, project, [sample(AUTH_FAILURES, str(i), datetime.now(UTC)) for i in range(8)])
    drain(database)
    with database.connect() as conn:
        alerts: dict[UUID, UUID] = dict(conn.execute(text("SELECT project_id,id FROM alert_summaries")).tuples().all())
    path = f"/api/v1/projects/{first}/incidents"
    with TestClient(create_app(engine=database), base_url=ORIGIN) as client:
        headers = login(client, owner)
        promotion = {"title":"Synthetic alert","alert_id":str(alerts[first])}
        assert client.post(path, headers=headers, json={**promotion,"alert_id":str(alerts[second])}).status_code == 404
        made = client.post(path, headers=headers, json=promotion)
        assert made.status_code == 201
        assert client.post(path, headers=headers, json=promotion).status_code == 409
        incident_id = UUID(made.json()["id"])
        timeline = client.get(f"{path}/{incident_id}").json()["timeline"]
        assert [r["action"] for r in timeline] == ["opened","alert_linked"]
        assert timeline[1]["new_value"] == promotion["alert_id"]
        evidence = client.get(f"/api/v1/projects/{first}/alerts/{alerts[first]}").json()["evidence"]
        assert len(evidence) == 8
        assert len(client.get(path).json()) == 1
        assert client.put(f"{path}/{incident_id}/alerts/{alerts[second]}",headers=headers,json={"version":2}).status_code == 404
    with pytest.raises(IntegrityError), transaction(database) as db:
        db.add(IncidentAlert(project_id=first, incident_id=incident_id, alert_id=alerts[second]))


def test_only_one_writer_can_use_an_incident_version(database: Engine) -> None:
    owner, _, org = add_user(database)
    project = make_project(database, org)
    path = f"/api/v1/projects/{project}/incidents"
    app = create_app(engine=database)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client, owner)
        made = client.post(path, headers=headers, json={"title":"Concurrent review"}).json()
        url = path + "/" + made["id"]
        barrier = Barrier(2)

        def write(note: str) -> int:
            barrier.wait(timeout=10)
            return client.post(url+"/notes", headers=headers, json={"version":1,"text":note}).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(write, ("first", "second"))) == [201, 409]
        assert len(client.get(url).json()["timeline"]) == 2
    with transaction(database) as db:
        assert db.scalar(select(Incident.version).where(Incident.id == UUID(made["id"]))) == 2
