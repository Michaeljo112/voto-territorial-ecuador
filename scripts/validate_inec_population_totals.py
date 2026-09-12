"""Validate INEC parish-level population totals against higher-level totals."""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "censo_inec" / "censo_inec_2022_tabulados.sqlite"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


METRICS = (
    "Número total de personas",
    "Sexo al nacer | Hombres",
    "Sexo al nacer | Mujeres",
)


@dataclass(frozen=True)
class Check:
    check_name: str
    metric: str
    geography: str
    expected: float
    observed: float

    @property
    def difference(self) -> float:
        return self.observed - self.expected

    @property
    def ok(self) -> bool:
        return abs(self.difference) < 0.000001


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"No existe la base: {db_path}\n"
            "Primero corre: python scripts/build_inec_censo_db.py"
        )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def scalar(conn: sqlite3.Connection, query: str, params: tuple[object, ...]) -> float:
    value = conn.execute(query, params).fetchone()[0]
    return float(value or 0)


def population_tabulado_id(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        select id
        from tabulados
        where slug = 'estructura_poblacional'
          and table_number = '1.2'
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("No encontre el tabulado estructura_poblacional 1.2")
    return int(row["id"])


def national_total(conn: sqlite3.Connection, tabulado_id: int, metric: str) -> float:
    return scalar(
        conn,
        """
        select value
        from observations
        where tabulado_id = ?
          and geography_level = 'nacional'
          and metric = ?
        """,
        (tabulado_id, metric),
    )


def sum_by_level(conn: sqlite3.Connection, tabulado_id: int, metric: str, level: str) -> float:
    return scalar(
        conn,
        """
        select sum(value)
        from observations
        where tabulado_id = ?
          and geography_level = ?
          and metric = ?
        """,
        (tabulado_id, level, metric),
    )


def level_checks(conn: sqlite3.Connection, tabulado_id: int) -> Iterable[Check]:
    for metric in METRICS:
        expected = national_total(conn, tabulado_id, metric)
        for level in ("provincia", "canton", "parroquia"):
            yield Check(
                check_name=f"suma_{level}_vs_nacional",
                metric=metric,
                geography="Ecuador",
                expected=expected,
                observed=sum_by_level(conn, tabulado_id, metric, level),
            )


def province_checks(conn: sqlite3.Connection, tabulado_id: int) -> Iterable[Check]:
    placeholders = ",".join("?" for _ in METRICS)
    query = f"""
    with provincia_total as (
        select provincia, metric, value as expected
        from observations
        where tabulado_id = ?
          and geography_level = 'provincia'
          and metric in ({placeholders})
    ),
    parroquia_sum as (
        select provincia, metric, sum(value) as observed
        from observations
        where tabulado_id = ?
          and geography_level = 'parroquia'
          and metric in ({placeholders})
        group by provincia, metric
    )
    select p.metric, p.provincia, p.expected, coalesce(s.observed, 0) as observed
    from provincia_total p
    left join parroquia_sum s
      on s.provincia = p.provincia
     and s.metric = p.metric
    order by p.metric, p.provincia
    """
    params = (tabulado_id, *METRICS, tabulado_id, *METRICS)
    for row in conn.execute(query, params):
        yield Check(
            check_name="suma_parroquias_vs_provincia",
            metric=row["metric"],
            geography=row["provincia"],
            expected=row["expected"],
            observed=row["observed"],
        )


def canton_checks(conn: sqlite3.Connection, tabulado_id: int) -> Iterable[Check]:
    placeholders = ",".join("?" for _ in METRICS)
    query = f"""
    with canton_total as (
        select provincia, canton, metric, value as expected
        from observations
        where tabulado_id = ?
          and geography_level = 'canton'
          and metric in ({placeholders})
    ),
    parroquia_sum as (
        select provincia, canton, metric, sum(value) as observed
        from observations
        where tabulado_id = ?
          and geography_level = 'parroquia'
          and metric in ({placeholders})
        group by provincia, canton, metric
    )
    select
        c.metric,
        c.provincia,
        c.canton,
        c.expected,
        coalesce(s.observed, 0) as observed
    from canton_total c
    left join parroquia_sum s
      on s.provincia = c.provincia
     and s.canton = c.canton
     and s.metric = c.metric
    order by c.metric, c.provincia, c.canton
    """
    params = (tabulado_id, *METRICS, tabulado_id, *METRICS)
    for row in conn.execute(query, params):
        yield Check(
            check_name="suma_parroquias_vs_canton",
            metric=row["metric"],
            geography=f"{row['provincia']} / {row['canton']}",
            expected=row["expected"],
            observed=row["observed"],
        )


def sex_sum_checks(conn: sqlite3.Connection, tabulado_id: int) -> Iterable[Check]:
    query = """
    with totals as (
        select geography_level, provincia, canton, parroquia, value as expected
        from observations
        where tabulado_id = ?
          and metric = 'Número total de personas'
    ),
    sex as (
        select
            geography_level,
            provincia,
            canton,
            parroquia,
            sum(value) as observed
        from observations
        where tabulado_id = ?
          and metric in ('Sexo al nacer | Hombres', 'Sexo al nacer | Mujeres')
        group by geography_level, provincia, canton, parroquia
    )
    select
        t.geography_level,
        t.provincia,
        t.canton,
        t.parroquia,
        t.expected,
        coalesce(s.observed, 0) as observed
    from totals t
    left join sex s
      on s.geography_level = t.geography_level
     and coalesce(s.provincia, '') = coalesce(t.provincia, '')
     and coalesce(s.canton, '') = coalesce(t.canton, '')
     and coalesce(s.parroquia, '') = coalesce(t.parroquia, '')
    order by abs(coalesce(s.observed, 0) - t.expected) desc
    """
    for row in conn.execute(query, (tabulado_id, tabulado_id)):
        geography = "Ecuador"
        if row["geography_level"] == "provincia":
            geography = row["provincia"]
        elif row["geography_level"] == "canton":
            geography = f"{row['provincia']} / {row['canton']}"
        elif row["geography_level"] == "parroquia":
            geography = f"{row['provincia']} / {row['canton']} / {row['parroquia']}"
        yield Check(
            check_name="hombres_mujeres_vs_total",
            metric="Número total de personas",
            geography=geography,
            expected=row["expected"],
            observed=row["observed"],
        )


def write_checks(checks: Iterable[Check], limit: int) -> int:
    all_checks = list(checks)
    failed = [check for check in all_checks if not check.ok]
    rows = failed if failed else all_checks[:limit]

    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(
        ["ok", "check", "metric", "geography", "expected", "observed", "difference"]
    )
    for check in rows[:limit]:
        writer.writerow(
            [
                "OK" if check.ok else "FAIL",
                check.check_name,
                check.metric,
                check.geography,
                f"{check.expected:.0f}",
                f"{check.observed:.0f}",
                f"{check.difference:.0f}",
            ]
        )

    print()
    print(f"checks_total,{len(all_checks)}")
    print(f"checks_failed,{len(failed)}")
    if failed and len(failed) > limit:
        print(f"failed_not_shown,{len(failed) - limit}")
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--scope",
        choices=("all", "levels", "provinces", "cantons", "sex"),
        default="all",
    )
    parser.add_argument("--limit", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with connect(args.db) as conn:
        tabulado_id = population_tabulado_id(conn)
        checks: list[Check] = []
        if args.scope in ("all", "levels"):
            checks.extend(level_checks(conn, tabulado_id))
        if args.scope in ("all", "provinces"):
            checks.extend(province_checks(conn, tabulado_id))
        if args.scope in ("all", "cantons"):
            checks.extend(canton_checks(conn, tabulado_id))
        if args.scope in ("all", "sex"):
            checks.extend(sex_sum_checks(conn, tabulado_id))
    return write_checks(checks, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
