from alembic import context
from sqlalchemy import text

from api_sentinel.audit import records as audit_records  # noqa: F401
from api_sentinel.database import open_engine
from api_sentinel.identity import models as identity_models  # noqa: F401
from api_sentinel.inventory import models as inventory_models  # noqa: F401
from api_sentinel.organizations.models import Base

if context.is_offline_mode():
    context.configure(dialect_name="postgresql", target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = open_engine()
    try:
        with engine.begin() as connection:
            # Serialize migration commands before Alembic reads the current revision.
            connection.execute(text("SELECT pg_advisory_xact_lock(173824, 1)"))
            context.configure(
                connection=connection, target_metadata=Base.metadata, compare_server_default=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
