import os
import subprocess
import sys
from pathlib import Path


def test_api_startup_loads_incident_foreign_keys() -> None:
    # Migration fixtures and worker imports can mask missing models in an API-only process.
    source = Path(__file__).resolve().parents[1] / "src"
    subprocess.run(
        [
            sys.executable,
            "-c",
            """from api_sentinel.main import create_app
from api_sentinel.incidents.models import IncidentAlert
create_app()
assert {key.column.table.name for key in IncidentAlert.__table__.foreign_keys} == {
    'incidents', 'alerts'
}
""",
        ],
        env={**os.environ, "PYTHONPATH": str(source)},
        check=True,
    )
