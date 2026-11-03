"""The cross-DB column types must resolve under Postgres, not just SQLite.

`JsonbOrJson` and `_UUID` pick a concrete type per dialect. The whole suite runs
on SQLite, so a fault in the *Postgres* branch is invisible to every other test —
which is exactly what happened: a global rename turned both Postgres branches
into `load_dialect_impl` calling itself, and every Postgres query raised
RecursionError while CI stayed green. Docker was broken and the tests said fine.

These tests compile the types against the Postgres dialect directly. No database
or driver connection is needed, so they run anywhere the suite runs.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.models.models import _UUID, AuditLog, ConsentRecord, JsonbOrJson, Patient

PG = postgresql.dialect()
LITE = sqlite.dialect()


class TestTypesResolvePerDialect:
    def test_json_type_resolves_on_postgres(self):
        """Must not recurse. Fails with RecursionError if the branch self-refers."""
        assert JsonbOrJson().dialect_impl(PG) is not None

    def test_uuid_type_resolves_on_postgres(self):
        assert _UUID().dialect_impl(PG) is not None

    def test_json_becomes_jsonb_on_postgres(self):
        compiled = JsonbOrJson().dialect_impl(PG).compile(dialect=PG)
        assert compiled == "JSONB"

    def test_uuid_becomes_native_uuid_on_postgres(self):
        compiled = _UUID().dialect_impl(PG).compile(dialect=PG)
        assert compiled == "UUID"

    def test_json_stays_json_on_sqlite(self):
        assert "JSON" in JsonbOrJson().dialect_impl(LITE).compile(dialect=LITE)

    def test_uuid_becomes_char_on_sqlite(self):
        assert "CHAR" in _UUID().dialect_impl(LITE).compile(dialect=LITE).upper()


class TestTablesCompileForPostgres:
    """Every mapped table must emit valid Postgres DDL."""

    @pytest.mark.parametrize("model", [Patient, ConsentRecord, AuditLog])
    def test_create_table_ddl_compiles(self, model):
        from sqlalchemy.schema import CreateTable

        ddl = str(CreateTable(model.__table__).compile(dialect=PG))
        assert model.__tablename__ in ddl

    def test_patient_id_is_a_uuid_column_on_postgres(self):
        from sqlalchemy.schema import CreateTable

        ddl = str(CreateTable(Patient.__table__).compile(dialect=PG))
        assert "UUID" in ddl.upper()

    def test_consent_scope_is_jsonb_on_postgres(self):
        from sqlalchemy.schema import CreateTable

        ddl = str(CreateTable(ConsentRecord.__table__).compile(dialect=PG))
        assert "JSONB" in ddl.upper()


class TestUuidRoundTrip:
    def test_uuid_binds_as_string(self):
        value = uuid.uuid4()
        bound = _UUID().process_bind_param(value, LITE)
        assert bound == str(value)

    def test_uuid_reads_back_as_uuid(self):
        value = uuid.uuid4()
        assert _UUID().process_result_value(str(value), LITE) == value

    def test_uuid_passthrough_when_already_a_uuid(self):
        """Postgres with as_uuid=True hands back a UUID, not a string."""
        value = uuid.uuid4()
        assert _UUID().process_result_value(value, PG) == value

    def test_none_is_preserved(self):
        assert _UUID().process_bind_param(None, LITE) is None
        assert _UUID().process_result_value(None, LITE) is None
