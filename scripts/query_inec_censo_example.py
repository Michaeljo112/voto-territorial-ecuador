"""Example queries for the INEC Ecuador 2022 census SQLite database."""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "censo_inec" / "censo_inec_2022_tabulados.sqlite"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"No existe la base: {db_path}\n"
            "Primero corre: python scripts/build_inec_censo_db.py"
        )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def print_rows(rows: Sequence[sqlite3.Row], columns: Sequence[str]) -> None:
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row[column] for column in columns])


def list_datasets(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        select slug, dominio, tema
        from datasets
        order by dominio, tema
        """
    ).fetchall()
    print_rows(rows, ["slug", "dominio", "tema"])


def list_tables(conn: sqlite3.Connection, slug: str) -> None:
    rows = conn.execute(
        """
        select table_number, csv_name, table_name
        from tabulados
        where slug = ?
        order by cast(replace(table_number, '.', '') as integer), table_number, csv_name
        """,
        (slug,),
    ).fetchall()
    print_rows(rows, ["table_number", "csv_name", "table_name"])


def query_parroquias(
    conn: sqlite3.Connection,
    slug: str,
    provincia: str | None,
    canton: str | None,
    parroquia: str | None,
    table_number: str | None,
    metric_like: str | None,
    limit: int,
) -> None:
    where = ["slug = ?"]
    params: list[object] = [slug]

    if provincia:
        where.append("provincia = ?")
        params.append(provincia)
    if canton:
        where.append("canton = ?")
        params.append(canton)
    if parroquia:
        where.append("parroquia = ?")
        params.append(parroquia)
    if table_number:
        where.append("table_number = ?")
        params.append(table_number)
    if metric_like:
        where.append("metric like ?")
        params.append(f"%{metric_like}%")

    params.append(limit)
    rows = conn.execute(
        f"""
        select
            tema,
            table_number,
            provincia,
            canton,
            parroquia,
            dimension_4,
            dimension_5,
            metric,
            value
        from v_observations_parroquia
        where {" and ".join(where)}
        order by provincia, canton, parroquia, table_number, dimension_4, dimension_5, metric
        limit ?
        """,
        params,
    ).fetchall()
    print_rows(
        rows,
        [
            "tema",
            "table_number",
            "provincia",
            "canton",
            "parroquia",
            "dimension_4",
            "dimension_5",
            "metric",
            "value",
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--list-datasets", action="store_true")
    parser.add_argument("--list-tables", metavar="SLUG")
    parser.add_argument("--slug", default="estructura_poblacional")
    parser.add_argument("--provincia", default="Azuay")
    parser.add_argument("--canton", default="Cuenca")
    parser.add_argument("--parroquia", default="Baños")
    parser.add_argument("--table-number", default="1.2")
    parser.add_argument("--metric-like")
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with connect(args.db) as conn:
        if args.list_datasets:
            list_datasets(conn)
        elif args.list_tables:
            list_tables(conn, args.list_tables)
        else:
            query_parroquias(
                conn,
                slug=args.slug,
                provincia=args.provincia,
                canton=args.canton,
                parroquia=args.parroquia,
                table_number=args.table_number,
                metric_like=args.metric_like,
                limit=args.limit,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
