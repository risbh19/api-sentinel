"""Correlate versioned findings and index their distinct surviving evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0009_alert_correlation"
down_revision = "0008_detection_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("rule_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.CheckConstraint("severity IN ('medium','low')", name="ck_alert_severity"),
        sa.CheckConstraint("status IN ('open','acknowledged','resolved')", name="ck_alert_status"),
    )
    op.create_index("ix_alert_project_bucket", "alerts", ["project_id", "bucket_start", "id"])
    op.add_column(
        "rule_findings",
        sa.Column(
            "alert_id",
            sa.Uuid(),
            sa.ForeignKey("alerts.id", name="fk_finding_alert", ondelete="CASCADE"),
        ),
    )
    op.create_index("ix_finding_alert", "rule_findings", ["alert_id"])
    op.create_table(
        "alert_evidence",
        sa.Column(
            "alert_id", sa.Uuid(), sa.ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("security_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    # The same function assigns historical and new findings. Epoch seconds keep
    # fingerprint encoding independent of timezone and database session settings.
    op.execute("""
        CREATE FUNCTION correlate_finding() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE e record; bucket bigint; signature text;
        BEGIN
          SELECT project_id, source_id, actor_hash, client_hash, method, route_template, occurred_at
            INTO STRICT e FROM security_events WHERE id = NEW.event_id;
          bucket := floor(extract(epoch FROM e.occurred_at) / NEW.window_seconds)::bigint * NEW.window_seconds;
          signature := encode(sha256(convert_to(jsonb_build_array(
            e.project_id, e.source_id, NEW.rule_key, NEW.version, bucket,
            CASE WHEN NEW.rule_key='high_request_volume' THEN e.client_hash ELSE e.actor_hash END,
            CASE WHEN NEW.rule_key='authorization_denials' THEN e.method END,
            CASE WHEN NEW.rule_key='authorization_denials' THEN e.route_template END
          )::text, 'UTF8')), 'hex');
          INSERT INTO alerts(project_id, source_id, rule_key, version, threshold, window_seconds,
                             bucket_start, fingerprint, severity)
            VALUES(e.project_id, e.source_id, NEW.rule_key, NEW.version, NEW.threshold,
                   NEW.window_seconds, to_timestamp(bucket), signature,
                   CASE WHEN NEW.rule_key='high_request_volume' THEN 'low' ELSE 'medium' END)
            ON CONFLICT (fingerprint) DO NOTHING;
          SELECT id INTO STRICT NEW.alert_id FROM alerts WHERE fingerprint = signature;
          RETURN NEW;
        END $$""")
    op.execute("""CREATE TRIGGER group_finding BEFORE INSERT OR UPDATE OF event_id
                  ON rule_findings FOR EACH ROW EXECUTE FUNCTION correlate_finding()""")
    op.execute("""
        CREATE FUNCTION sync_alert_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          -- Project deletion cascades through both parent tables. The FK already
          -- removes every link for a deleted alert, including for the app role.
          IF TG_OP = 'DELETE' AND NOT EXISTS (SELECT 1 FROM alerts WHERE id=OLD.alert_id) THEN
            RETURN NULL;
          END IF;
          IF TG_OP <> 'DELETE' THEN
            INSERT INTO alert_evidence(alert_id, event_id)
              SELECT NEW.alert_id, e.id FROM security_events e JOIN alerts a
                ON a.id=NEW.alert_id AND a.project_id=e.project_id AND a.source_id=e.source_id
              WHERE e.id=ANY(NEW.evidence)
              ON CONFLICT DO NOTHING;
          END IF;
          IF TG_OP <> 'INSERT' AND OLD.alert_id IS NOT NULL THEN
            DELETE FROM alert_evidence ae
              WHERE ae.alert_id=OLD.alert_id AND ae.event_id=ANY(OLD.evidence)
                AND NOT EXISTS (SELECT 1 FROM rule_findings f WHERE f.alert_id=ae.alert_id
                                AND ae.event_id=ANY(f.evidence));
          END IF;
          RETURN NULL;
        END $$""")
    op.execute("""CREATE TRIGGER update_alert_evidence AFTER INSERT OR UPDATE OR DELETE
                  ON rule_findings FOR EACH ROW EXECUTE FUNCTION sync_alert_evidence()""")
    op.execute("UPDATE rule_findings SET event_id=event_id")
    op.alter_column("rule_findings", "alert_id", nullable=False)
    op.execute("""
        CREATE VIEW alert_summaries AS
        SELECT a.*, f.first_seen, f.last_seen, f.occurrence_count
          FROM alerts a JOIN LATERAL (
            SELECT min(e.occurred_at) first_seen, max(e.occurred_at) last_seen,
                   count(*) occurrence_count
              FROM rule_findings r JOIN security_events e ON e.id=r.event_id
              WHERE r.alert_id=a.id AND e.project_id=a.project_id HAVING count(*) > 0
          ) f ON true""")


def downgrade() -> None:
    op.execute("DROP VIEW alert_summaries")
    op.execute("DROP TRIGGER update_alert_evidence ON rule_findings")
    op.execute("DROP FUNCTION sync_alert_evidence()")
    op.execute("DROP TRIGGER group_finding ON rule_findings")
    op.execute("DROP FUNCTION correlate_finding()")
    op.drop_table("alert_evidence")
    op.drop_column("rule_findings", "alert_id")
    op.drop_table("alerts")
