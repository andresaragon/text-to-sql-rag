"""Activos de Oracle: scripts SQL, compose, workflow y documentación (SPEC.md, CA6).

Escritas antes de implementar (rojas por diseño); no se editan para hacerlas pasar.
Son comprobaciones estáticas: no necesitan Oracle (eso vive en tests/integration/).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL_FILES = ["db/oracle/01_users.sql", "db/oracle/02_schema.sql", "db/oracle/03_seed.sql"]
TABLES = ["customers", "invoices", "payments", "collection_actions"]
IMAGE = "gvenzl/oracle-free:23.26.3-slim-faststart"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def all_sql() -> str:
    return "\n".join(read(p) for p in SQL_FILES)


def statements(text: str) -> list[str]:
    no_comments = re.sub(r"--[^\n]*", "", text)
    return [s.strip() for s in no_comments.split(";") if s.strip()]


# --------------------------------------------------------------- dependencias y entorno
def test_oracledb_is_pinned_in_the_requirements():
    assert re.search(r"(?m)^oracledb==26\.0\.1\s*(#.*)?$", read("requirements.txt"))


def test_env_example_documents_the_target_url():
    assert "TARGET_DATABASE_URL" in read(".env.example")


# --------------------------------------------------------------------- scripts SQL
def test_the_sql_scripts_exist():
    for path in SQL_FILES:
        assert (ROOT / path).is_file(), path


@pytest.mark.parametrize("path", SQL_FILES)
def test_every_script_switches_to_the_pdb_before_anything_else(path):
    # La imagen ejecuta los scripts en CDB$ROOT; sin esto las cuentas no pueden entrar al PDB (ORA-01045).
    first = statements(read(path))[0]
    assert re.fullmatch(r"(?is)ALTER\s+SESSION\s+SET\s+CONTAINER\s*=\s*FREEPDB1", first), first


def test_the_owner_and_the_reader_accounts_are_created_with_the_demo_passwords():
    sql = read("db/oracle/01_users.sql")
    assert re.search(r"(?i)CREATE USER\s+SALES\b", sql)
    assert re.search(r"(?i)CREATE USER\s+APP_RO\b", sql)
    assert "sales-demo-pw" in sql and "app-ro-demo-pw" in sql
    assert re.search(r"(?i)QUOTA UNLIMITED ON\s+USERS", sql)


def _grants(text: str):
    for statement in statements(text):
        match = re.match(r"(?is)GRANT\s+(.*?)\s+(?:ON\s+\S+\s+)?TO\s+(\w+)\s*$", statement)
        if match:
            privileges = {p.strip().upper() for p in match.group(1).split(",")}
            yield privileges, match.group(2).upper(), statement


def test_the_reader_has_only_create_session_and_select():
    grants = [g for g in _grants(all_sql()) if g[1] == "APP_RO"]
    assert grants
    for privileges, _, statement in grants:
        assert privileges <= {"CREATE SESSION", "SELECT"}, statement
    assert any("CREATE SESSION" in privileges for privileges, _, _ in grants)


def test_the_owner_has_only_what_it_needs_to_create_the_tables():
    grants = [g for g in _grants(all_sql()) if g[1] == "SALES"]
    assert grants
    for privileges, _, statement in grants:
        assert privileges <= {"CREATE SESSION", "CREATE TABLE", "CREATE SEQUENCE"}, statement


def test_no_public_execute_or_broad_roles_are_granted():
    for statement in statements(all_sql()):
        if re.match(r"(?i)GRANT\b", statement):
            assert not re.search(r"(?i)\bTO\s+PUBLIC\b", statement), statement
            assert not re.search(r"(?i)\bEXECUTE\b", statement), statement
            assert not re.search(r"(?i)\b(DBA|RESOURCE|CONNECT)\b", statement), statement


def test_the_schema_has_the_four_tables_without_postgres_leftovers():
    sql = read("db/oracle/02_schema.sql")
    created = {m.lower() for m in re.findall(r"(?i)CREATE TABLE\s+(?:SALES\.)?(\w+)", sql)}
    assert created == set(TABLES)
    assert re.search(r"(?i)GENERATED\s+(BY DEFAULT|ALWAYS)\s+AS\s+IDENTITY", sql)
    assert "VARCHAR2" in sql.upper() and re.search(r"(?i)CHECK\s*\(\s*status\s+IN", sql)
    for leftover in (r"(?i)\bSERIAL\b", r"(?i)\bVECTOR\b", r"(?i)schema_embeddings", r"(?i)\bNOW\(\)", r"::"):
        assert not re.search(leftover, sql), leftover


def test_the_reader_can_select_each_of_the_four_tables():
    grants = [(p, s) for p, who, s in _grants(all_sql()) if who == "APP_RO" and "SELECT" in p]
    for table in TABLES:
        assert any(re.search(rf"(?i)ON\s+(?:SALES\.)?{table}\b", statement) for _, statement in grants), table


def test_the_seed_matches_the_postgres_sample_data():
    sql = read("db/oracle/03_seed.sql")
    for needle in ("Ana Torres", "Marco Rossi", "Luisa Fernandez", "bank_transfer", "email_reminder"):
        assert needle in sql, needle


# ------------------------------------------------------------------------- compose
def _compose(*files: str) -> dict:
    if shutil.which("docker") is None:
        pytest.skip("docker no está disponible")
    command = ["docker", "compose"]
    for name in files:
        command += ["-f", name]
    out = subprocess.run([*command, "config", "--format", "json"], cwd=ROOT, capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_oracle_override_is_a_valid_compose_project():
    config = _compose("docker-compose.yml", "docker-compose.oracle.yml")
    assert {"db", "indexer", "api", "oracle"} <= set(config["services"])


def test_the_oracle_service_is_pinned_healthy_and_local_only():
    oracle = _compose("docker-compose.yml", "docker-compose.oracle.yml")["services"]["oracle"]
    assert oracle["image"] == IMAGE
    assert "healthcheck.sh" in " ".join(oracle["healthcheck"]["test"])
    assert oracle["environment"]["ORACLE_PASSWORD"] == "oracle-demo-admin-pw"
    assert all(p.get("host_ip") == "127.0.0.1" and str(p["target"]) == "1521" for p in oracle["ports"])
    init = [v for v in oracle["volumes"] if v.get("target") == "/container-entrypoint-initdb.d"]
    assert init and init[0].get("read_only") is True and init[0]["source"].endswith("db/oracle")


def test_the_api_and_the_indexer_target_oracle_when_the_override_is_used():
    services = _compose("docker-compose.yml", "docker-compose.oracle.yml")["services"]
    api, indexer = services["api"], services["indexer"]
    assert api["environment"]["TARGET_DIALECT"] == "oracle"
    assert api["environment"]["TARGET_DATABASE_URL"].startswith("oracle+oracledb://app_ro:app-ro-demo-pw@oracle:1521/")
    assert "service_name=FREEPDB1" in api["environment"]["TARGET_DATABASE_URL"]
    assert api["environment"]["ALLOWED_SCHEMA"] == "SALES"
    assert indexer["environment"]["TARGET_DIALECT"] == "oracle"
    assert indexer["environment"]["ALLOWED_SCHEMA"] == "SALES"
    assert api["depends_on"]["oracle"]["condition"] == "service_healthy"


def test_the_base_compose_file_is_unchanged_and_has_no_oracle():
    services = _compose("docker-compose.yml")["services"]
    assert "oracle" not in services
    assert services["api"]["environment"].get("TARGET_DIALECT") != "oracle"


# ---------------------------------------------------------------- workflow y documentos
def test_the_integration_workflow_is_manual_only():
    text = read(".github/workflows/oracle-integration.yml")
    assert "workflow_dispatch" in text
    assert not re.search(r"(?m)^\s*(push|pull_request|schedule)\s*:", text)
    assert "ORACLE_INTEGRATION" in text and "pytest" in text and "docker compose" in text
    assert "download.pytorch.org/whl/cpu" in text


def test_the_readmes_explain_how_to_run_against_oracle():
    english, spanish = read("README.md"), read("README.es.md")
    assert "Run against Oracle" in english and "Ejecutar contra Oracle" in spanish
    for text in (english, spanish):
        assert "docker-compose.oracle.yml" in text
        assert "4 GB" in text


def test_the_oracle_firewall_doc_describes_the_execution():
    doc = read("docs/oracle-firewall.md")
    assert re.search(r"(?m)^##\s+Execution\b", doc)
    for needle in ("call_timeout", "READ ONLY", "DPY-4024", "ORA-01466"):
        assert needle in doc, needle
