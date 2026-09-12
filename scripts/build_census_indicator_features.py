"""Build parish-level feature matrices from all INEC census tabulated indicators."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

from build_parish_model_dataset import build_ordered_census_crosswalk, slugify


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CENSUS_DB = ROOT / "data" / "censo_inec" / "censo_inec_2022_tabulados.sqlite"
DEFAULT_ADM3 = ROOT / "data" / "ecu_adm_2024" / "ecu_adm_adm3_2024.shp"
DEFAULT_OUT_DIR = ROOT / "data" / "model"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def slug_series(series: pd.Series) -> pd.Series:
    return series.fillna("").map(slugify)


def generic_dimension_series(df: pd.DataFrame, column: str) -> pd.Series:
    dim = slug_series(df[column])
    provincia = slug_series(df["provincia"])
    canton = slug_series(df["canton"])
    parroquia = slug_series(df["parroquia"])
    is_same_geo = dim.eq(provincia) | dim.eq(canton) | dim.eq(parroquia)
    is_total_geo = (
        dim.eq("total_" + provincia)
        | dim.eq("total_" + canton)
        | dim.eq("total_" + parroquia)
    )
    dim = dim.mask(is_same_geo, "misma_geografia")
    dim = dim.mask(is_total_geo, "total_geografia")
    return dim


def add_feature_id(chunk: pd.DataFrame) -> pd.DataFrame:
    parts = pd.DataFrame(
        {
            "prefix": "censo_ind",
            "slug": slug_series(chunk["slug"]),
            "table": slug_series(chunk["table_number"]).replace("", "sin_numero"),
            "dim4": generic_dimension_series(chunk, "dimension_4"),
            "dim5": generic_dimension_series(chunk, "dimension_5"),
            "metric": slug_series(chunk["metric"]),
        }
    )
    chunk = chunk.copy()
    chunk["feature_id"] = (
        parts["prefix"]
        + "_"
        + parts["slug"]
        + "_"
        + parts["table"]
        + "_"
        + parts["dim4"]
        + "_"
        + parts["dim5"]
        + "_"
        + parts["metric"]
    ).str.replace(r"_+", "_", regex=True).str.strip("_")
    return chunk


def init_output_db(path: Path) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        pragma journal_mode = wal;
        pragma synchronous = normal;
        create table indicator_long (
            ADM3_PCODE text not null,
            feature_id text not null,
            value real
        );
        create table indicator_dictionary (
            feature_id text not null,
            slug text,
            table_number text,
            table_name text,
            dimension_4 text,
            dimension_5 text,
            metric text
        );
        """
    )
    return conn


def write_long_indicators(
    census_db: Path,
    out_sqlite: Path,
    adm3_path: Path,
    chunksize: int,
) -> tuple[int, int, int]:
    with sqlite3.connect(census_db) as census_conn:
        crosswalk, _ = build_ordered_census_crosswalk(census_conn, adm3_path)
        query = """
        select
            o.slug,
            t.table_number,
            t.table_name,
            o.provincia,
            o.canton,
            o.parroquia,
            o.dimension_4,
            o.dimension_5,
            o.metric,
            o.value
        from observations o
        join tabulados t on t.id = o.tabulado_id
        where o.geography_level = 'parroquia'
          and o.value is not null
        """
        out_conn = init_output_db(out_sqlite)
        rows_written = 0
        dict_rows = 0
        feature_count = 0
        try:
            for idx, chunk in enumerate(pd.read_sql_query(query, census_conn, chunksize=chunksize), start=1):
                chunk = add_feature_id(chunk)
                chunk = chunk.merge(
                    crosswalk,
                    on=["provincia", "canton", "parroquia"],
                    how="left",
                    validate="many_to_one",
                )
                values = chunk[["ADM3_PCODE", "feature_id", "value"]].dropna(subset=["ADM3_PCODE"])
                dictionary = chunk[
                    [
                        "feature_id",
                        "slug",
                        "table_number",
                        "table_name",
                        "dimension_4",
                        "dimension_5",
                        "metric",
                    ]
                ].drop_duplicates()
                values.to_sql("indicator_long", out_conn, if_exists="append", index=False)
                dictionary.to_sql("indicator_dictionary", out_conn, if_exists="append", index=False)
                rows_written += len(values)
                dict_rows += len(dictionary)
                print(f"chunk,{idx},rows,{rows_written}", flush=True)

            out_conn.executescript(
                """
                create table indicator_values as
                select ADM3_PCODE, feature_id, avg(value) as value
                from indicator_long
                group by ADM3_PCODE, feature_id;

                create table indicator_dictionary_unique as
                select
                    feature_id,
                    min(slug) as slug,
                    min(table_number) as table_number,
                    min(table_name) as table_name,
                    min(dimension_4) as dimension_4,
                    min(dimension_5) as dimension_5,
                    min(metric) as metric
                from indicator_dictionary
                group by feature_id;

                create index idx_indicator_values_feature on indicator_values(feature_id);
                create index idx_indicator_values_adm3 on indicator_values(ADM3_PCODE);
                """
            )
            feature_count = out_conn.execute("select count(*) from indicator_dictionary_unique").fetchone()[0]
            out_conn.commit()
        finally:
            out_conn.close()
    return rows_written, dict_rows, int(feature_count)


def build_wide_matrix(out_sqlite: Path, min_completeness: float) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    conn = sqlite3.connect(out_sqlite)
    try:
        parish_count = conn.execute("select count(distinct ADM3_PCODE) from indicator_values").fetchone()[0]
        min_non_missing = int(parish_count * min_completeness)
        selected = pd.read_sql_query(
            """
            select feature_id, count(*) as non_missing
            from indicator_values
            group by feature_id
            having count(*) >= ?
            order by feature_id
            """,
            conn,
            params=(min_non_missing,),
        )
        selected_features = selected["feature_id"].tolist()
        if not selected_features:
            raise RuntimeError("Ningun indicador supera el umbral de completitud.")

        placeholders = ",".join("?" for _ in selected_features)
        long_selected = pd.read_sql_query(
            f"""
            select ADM3_PCODE, feature_id, value
            from indicator_values
            where feature_id in ({placeholders})
            """,
            conn,
            params=selected_features,
        )
        wide = (
            long_selected.pivot_table(
                index="ADM3_PCODE",
                columns="feature_id",
                values="value",
                aggfunc="first",
            )
            .reset_index()
            .rename_axis(None, axis=1)
        )
        dictionary = pd.read_sql_query(
            """
            select d.*, s.non_missing
            from indicator_dictionary_unique d
            join (
                select feature_id, count(*) as non_missing
                from indicator_values
                group by feature_id
                having count(*) >= ?
            ) s on s.feature_id = d.feature_id
            order by d.feature_id
            """,
            conn,
            params=(min_non_missing,),
        )
        report = pd.DataFrame(
            [
                {"check": "parish_rows_with_any_indicator", "value": parish_count},
                {"check": "min_completeness", "value": min_completeness},
                {"check": "wide_features_selected", "value": len(selected_features)},
                {"check": "wide_rows", "value": len(wide)},
                {
                    "check": "wide_mean_missing_pct",
                    "value": float(wide[selected_features].isna().mean().mean()),
                },
            ]
        )
    finally:
        conn.close()
    return wide, dictionary, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census-db", type=Path, default=DEFAULT_CENSUS_DB)
    parser.add_argument("--adm3", type=Path, default=DEFAULT_ADM3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--chunksize", type=int, default=250_000)
    parser.add_argument("--min-completeness", type=float, default=0.95)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_sqlite = args.out_dir / "census_indicator_long.sqlite"

    rows_written, dict_rows, feature_count = write_long_indicators(
        args.census_db,
        out_sqlite,
        args.adm3,
        args.chunksize,
    )
    wide, dictionary, report = build_wide_matrix(out_sqlite, args.min_completeness)
    report = pd.concat(
        [
            report,
            pd.DataFrame(
                [
                    {"check": "long_rows_written", "value": rows_written},
                    {"check": "dictionary_rows_written", "value": dict_rows},
                    {"check": "all_raw_feature_ids", "value": feature_count},
                ]
            ),
        ],
        ignore_index=True,
    )

    features_path = args.out_dir / "census_indicator_features.csv"
    dictionary_path = args.out_dir / "census_indicator_dictionary.csv"
    report_path = args.out_dir / "census_indicator_report.csv"
    wide.to_csv(features_path, index=False, encoding="utf-8")
    dictionary.to_csv(dictionary_path, index=False, encoding="utf-8")
    report.to_csv(report_path, index=False, encoding="utf-8")

    print(report.to_csv(index=False), end="")
    print(f"\nLong SQLite: {out_sqlite}")
    print(f"Features: {features_path}")
    print(f"Dictionary: {dictionary_path}")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
