\getenv probe_password SENTINEL_PROBE_PASSWORD
CREATE ROLE sentinel_probe LOGIN PASSWORD :'probe_password';
REVOKE ALL ON DATABASE sentinel FROM PUBLIC;
GRANT CONNECT ON DATABASE sentinel TO sentinel_probe;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
