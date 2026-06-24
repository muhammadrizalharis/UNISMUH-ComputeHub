"""Migrasi skema RINGAN (additive) untuk SQLite.

Bukan pengganti Alembic penuh, tetapi cukup untuk lingkungan non-admin di mana
skema berkembang dengan PENAMBAHAN kolom. Operasi yang dilakukan HANYA
`ALTER TABLE ... ADD COLUMN` (tidak pernah drop/rename), sehingga aman terhadap
data lama. Untuk DB eksternal (mis. PostgreSQL) gunakan migrasi sungguhan.

Dipakai di `init_db()` setelah `create_all`: kolom baru pada model yang belum ada
di tabel lama akan ditambahkan otomatis.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.core.logging import get_logger

logger = get_logger(__name__)


def _default_sql(column) -> str | None:
    """Hasilkan literal DEFAULT SQL dari definisi kolom (atau None)."""
    server_default = column.server_default
    if server_default is not None:
        arg = getattr(server_default, "arg", None)
        if arg is not None:
            return getattr(arg, "text", None) or str(arg)

    default = column.default
    if default is not None and getattr(default, "is_scalar", False):
        val = default.arg
        if isinstance(val, bool):
            return "1" if val else "0"
        if isinstance(val, (int, float)):
            return str(val)
        # Enum (subclass str) atau string biasa.
        sval = val.value if hasattr(val, "value") else val
        if isinstance(sval, bool):
            return "1" if sval else "0"
        if isinstance(sval, (int, float)):
            return str(sval)
        esc = str(sval).replace("'", "''")
        return f"'{esc}'"
    return None


def _column_ddl(column, dialect) -> str | None:
    """Bangun potongan DDL untuk satu kolom: `\"nama\" TIPE [DEFAULT ..] [NOT NULL]`."""
    try:
        type_sql = column.type.compile(dialect=dialect)
    except Exception:  # noqa: BLE001
        return None
    parts = [f'"{column.name}"', type_sql]
    default_sql = _default_sql(column)
    if default_sql is not None:
        parts.append(f"DEFAULT {default_sql}")
    # SQLite menolak ADD COLUMN NOT NULL tanpa default pada tabel berisi data,
    # jadi NOT NULL hanya dipasang bila ada default.
    if not column.nullable:
        if default_sql is not None:
            parts.append("NOT NULL")
        else:
            logger.warning(
                "Kolom %s ditambahkan sebagai NULLABLE (tak ada default untuk NOT NULL).",
                column.name,
            )
    return " ".join(parts)


def sync_sqlite_schema(connection: Connection, metadata) -> list[str]:
    """Tambahkan kolom yang hilang pada tabel SQLite yang sudah ada.

    Mengembalikan daftar `tabel.kolom` yang ditambahkan.
    """
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    dialect = connection.dialect
    applied: list[str] = []

    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # tabel baru sudah dibuat oleh create_all
        existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_cols:
                continue
            ddl = _column_ddl(column, dialect)
            if ddl is None:
                logger.warning(
                    "Lewati %s.%s (DDL tidak bisa dibuat).", table.name, column.name
                )
                continue
            connection.execute(
                text(f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}')
            )
            applied.append(f"{table.name}.{column.name}")
    return applied
