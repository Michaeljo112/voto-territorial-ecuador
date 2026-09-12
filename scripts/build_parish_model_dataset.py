"""Build a parish-level modeling table from satellite, census, and election data."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CENSUS_DB = ROOT / "data" / "censo_inec" / "censo_inec_2022_tabulados.sqlite"
DEFAULT_OUT_DIR = ROOT / "data" / "model"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def strip_accents(value: object) -> str:
    text = str(value or "")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def slugify(value: object) -> str:
    text = strip_accents(value)
    text = text.replace("\n", " ").replace("\r", " ")
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()
    return re.sub(r"_+", "_", text)


def parse_number_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return series
    cleaned = (
        series.astype(str)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.replace("%", "", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [slugify(col) for col in df.columns]
    return df


def load_satellite(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="data")
    df = clean_columns(df)
    rename = {
        "adm3_pcode": "ADM3_PCODE",
        "a_o": "anio_sat",
        "ano": "anio_sat",
        "provincia": "provincia_sat",
        "canton": "canton_sat",
        "parroquia": "parroquia_sat",
        "personas": "sat_personas",
        "no_pobres": "sat_no_pobres",
        "pobres": "sat_pobres",
    }
    df = df.rename(columns=rename)
    for col in df.columns:
        if col != "ADM3_PCODE" and col not in {"provincia_sat", "canton_sat", "parroquia_sat"}:
            df[col] = parse_number_series(df[col])
    df["sat_pobreza_pct"] = df["sat_pobres"] / df["sat_personas"]
    return df


def read_election_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", engine="python", encoding="utf-8")
    df = clean_columns(df)
    if "adm3_pcode" in df.columns:
        df = df.rename(columns={"adm3_pcode": "ADM3_PCODE"})
    for col in df.columns:
        if col not in {"ADM3_PCODE", "junta_sexo"}:
            df[col] = parse_number_series(df[col])
    return df


def load_elections(data_dir: Path) -> pd.DataFrame:
    specs = [
        ("v1", data_dir / "1era.csv"),
        ("v2", data_dir / "2da.csv"),
        ("v1_f", data_dir / "1raF.csv"),
        ("v1_m", data_dir / "1raM.csv"),
        ("v2_f", data_dir / "2daF.csv"),
        ("v2_m", data_dir / "2daM.csv"),
    ]
    frames: list[pd.DataFrame] = []
    for prefix, path in specs:
        df = read_election_csv(path)
        if "junta_sexo" in df.columns:
            df = df.drop(columns=["junta_sexo"])
        df = df.rename(columns={col: f"elec_{prefix}_{col}" for col in df.columns if col != "ADM3_PCODE"})
        frames.append(df)

    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on="ADM3_PCODE", how="outer", validate="one_to_one")

    for prefix in ("v1", "v2", "v1_f", "v1_m", "v2_f", "v2_m"):
        noboa = next((c for c in merged.columns if c.startswith(f"elec_{prefix}_daniel_noboa")), None)
        luisa = next((c for c in merged.columns if c.startswith(f"elec_{prefix}_luisa_gonzalez")), None)
        if noboa and luisa:
            merged[f"elec_{prefix}_noboa_minus_luisa"] = merged[noboa] - merged[luisa]
    if "elec_v2_noboa_minus_luisa" in merged.columns:
        merged["target_v2_noboa_win"] = (merged["elec_v2_noboa_minus_luisa"] > 0).astype("Int64")
    return merged


def census_parish_population(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        select
            row_number,
            provincia,
            canton,
            parroquia,
            metric,
            value
        from observations o
        join tabulados t on t.id = o.tabulado_id
        where o.slug = 'estructura_poblacional'
          and t.table_number = '1.2'
          and o.geography_level = 'parroquia'
          and o.metric in (
              'Número total de personas',
              'Sexo al nacer | Hombres',
              'Sexo al nacer | Mujeres'
          )
        """,
        conn,
    )


def build_ordered_census_crosswalk(conn: sqlite3.Connection, adm3_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    pop_long = census_parish_population(conn)
    totals = (
        pop_long[pop_long["metric"] == "Número total de personas"]
        .sort_values("row_number")
        .reset_index(drop=True)
    )
    adm3 = gpd.read_file(adm3_path).drop(columns="geometry").reset_index(drop=True)
    report_rows = []
    report_rows.append({"check": "census_parish_rows", "value": len(totals)})
    report_rows.append({"check": "adm3_rows", "value": len(adm3)})

    if len(totals) != len(adm3):
        raise RuntimeError(
            f"No puedo usar orden DPA: censo tiene {len(totals)} filas parroquiales "
            f"y adm3 tiene {len(adm3)} filas."
        )

    crosswalk = pd.concat([adm3[["ADM3_PCODE"]], totals[["provincia", "canton", "parroquia"]]], axis=1)
    return crosswalk, pd.DataFrame(report_rows)


def load_census_features(conn: sqlite3.Connection, crosswalk: pd.DataFrame) -> pd.DataFrame:
    pop = census_parish_population(conn)
    pop_wide = (
        pop.pivot_table(
            index=["provincia", "canton", "parroquia"],
            columns="metric",
            values="value",
            aggfunc="first",
        )
        .reset_index()
        .rename(
            columns={
                "Número total de personas": "censo_personas",
                "Sexo al nacer | Hombres": "censo_hombres",
                "Sexo al nacer | Mujeres": "censo_mujeres",
            }
        )
    )
    pop_wide["censo_hombres_pct"] = pop_wide["censo_hombres"] / pop_wide["censo_personas"]
    pop_wide["censo_mujeres_pct"] = pop_wide["censo_mujeres"] / pop_wide["censo_personas"]

    age = pd.read_sql_query(
        """
        select provincia, canton, parroquia, dimension_4 as grupo_edad, metric, value
        from v_observations_parroquia
        where slug = 'estructura_poblacional'
          and table_number = '2.1'
          and metric = 'Número total de personas'
          and dimension_4 is not null
        """,
        conn,
    )
    age = age[
        age["grupo_edad"].str.match(r"^(De \d+-\d+|85 o más)$", na=False)
    ].copy()
    age["age_feature"] = "censo_edad_" + age["grupo_edad"].map(slugify)
    age_wide = (
        age.pivot_table(
            index=["provincia", "canton", "parroquia"],
            columns="age_feature",
            values="value",
            aggfunc="first",
        )
        .reset_index()
    )
    age_cols = [col for col in age_wide.columns if col.startswith("censo_edad_")]
    age_total = age_wide[age_cols].sum(axis=1)
    age_pct = age_wide[age_cols].div(age_total, axis=0)
    age_pct.columns = [f"{col}_pct" for col in age_pct.columns]
    age_wide = pd.concat(
        [age_wide[["provincia", "canton", "parroquia"]], age_pct],
        axis=1,
    )

    census = pop_wide.merge(age_wide, on=["provincia", "canton", "parroquia"], how="left", validate="one_to_one")
    nbi = load_nbi_features(conn)
    census = census.merge(nbi, on=["provincia", "canton", "parroquia"], how="left", validate="one_to_one")
    census = crosswalk.merge(census, on=["provincia", "canton", "parroquia"], how="left", validate="one_to_one")
    census = census.rename(
        columns={
            "provincia": "provincia_censo",
            "canton": "canton_censo",
            "parroquia": "parroquia_censo",
        }
    )
    return census


def load_nbi_features(conn: sqlite3.Connection) -> pd.DataFrame:
    nbi = pd.read_sql_query(
        """
        select provincia, canton, parroquia, dimension_4, metric, value
        from v_observations_parroquia
        where slug = 'pobreza_nbi'
          and table_number = '1.2'
          and dimension_4 like 'Total %'
        """,
        conn,
    )
    nbi["metric_clean"] = nbi["metric"].str.replace("\n", " ", regex=False)
    group_cols = ["provincia", "canton", "parroquia"]

    persons = (
        nbi[nbi["metric_clean"].eq("Número total de personas en viviendas particulares")]
        .groupby(group_cols, as_index=False)["value"]
        .first()
        .rename(columns={"value": "censo_nbi_personas_viviendas_particulares"})
    )
    poor = (
        nbi[
            nbi["metric_clean"].str.contains(" | Pobres | Sexo al nacer | ", regex=False)
            & ~nbi["metric_clean"].str.contains("No pobres", regex=False)
        ]
        .groupby(group_cols, as_index=False)["value"]
        .sum()
        .rename(columns={"value": "censo_nbi_pobres"})
    )
    nonpoor = (
        nbi[nbi["metric_clean"].str.contains(" | No pobres | Sexo al nacer | ", regex=False)]
        .groupby(group_cols, as_index=False)["value"]
        .sum()
        .rename(columns={"value": "censo_nbi_no_pobres"})
    )
    out = persons.merge(poor, on=group_cols, how="outer").merge(nonpoor, on=group_cols, how="outer")
    out["censo_nbi_pobreza_pct"] = out["censo_nbi_pobres"] / out["censo_nbi_personas_viviendas_particulares"]
    return out


def build_issue_report(df: pd.DataFrame) -> pd.DataFrame:
    issues: list[pd.DataFrame] = []
    missing_election = df[df.filter(like="elec_v2_").isna().all(axis=1)].copy()
    if not missing_election.empty:
        missing_election["issue"] = "missing_election"
        issues.append(missing_election)

    pop_diff = df[(df["censo_personas"] - df["sat_personas"]).abs() > 0].copy()
    if not pop_diff.empty:
        pop_diff["issue"] = "sat_personas_differs_from_total_population"
        issues.append(pop_diff)

    nbi_diff = df[
        (df["censo_nbi_personas_viviendas_particulares"] - df["sat_personas"]).abs() > 0
    ].copy()
    if not nbi_diff.empty:
        nbi_diff["issue"] = "sat_personas_differs_from_census_nbi_persons"
        issues.append(nbi_diff)

    if not issues:
        return pd.DataFrame(columns=["issue", "ADM3_PCODE"])

    cols = [
        "issue",
        "ADM3_PCODE",
        "provincia_sat",
        "canton_sat",
        "parroquia_sat",
        "sat_personas",
        "censo_personas",
        "censo_nbi_personas_viviendas_particulares",
        "censo_personas_minus_sat_personas",
        "censo_nbi_personas_minus_sat_personas",
    ]
    return pd.concat(issues, ignore_index=True)[cols]


def build_dataset(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    satellite = load_satellite(args.satellite)
    elections = load_elections(args.data_dir)
    with sqlite3.connect(args.census_db) as conn:
        crosswalk, crosswalk_report = build_ordered_census_crosswalk(conn, args.adm3)
        census = load_census_features(conn, crosswalk)

    df = satellite.merge(elections, on="ADM3_PCODE", how="left", validate="one_to_one")
    df = df.merge(census, on="ADM3_PCODE", how="left", validate="one_to_one")
    if args.include_census_indicators:
        indicators = pd.read_csv(args.census_indicators)
        df = df.merge(indicators, on="ADM3_PCODE", how="left", validate="one_to_one")
    df["censo_personas_minus_sat_personas"] = df["censo_personas"] - df["sat_personas"]
    df["censo_nbi_personas_minus_sat_personas"] = (
        df["censo_nbi_personas_viviendas_particulares"] - df["sat_personas"]
    )
    df["censo_nbi_pobres_minus_sat_pobres"] = df["censo_nbi_pobres"] - df["sat_pobres"]

    report = [
        {"check": "satellite_rows", "value": len(satellite)},
        {"check": "satellite_unique_adm3", "value": satellite["ADM3_PCODE"].nunique()},
        {"check": "election_rows", "value": len(elections)},
        {"check": "census_rows", "value": len(census)},
        {"check": "final_rows", "value": len(df)},
        {"check": "missing_election", "value": int(df.filter(like="elec_v2_").isna().all(axis=1).sum())},
        {"check": "missing_census", "value": int(df["censo_personas"].isna().sum())},
        {
            "check": "census_indicator_features",
            "value": len([col for col in df.columns if col.startswith("censo_ind_")]),
        },
        {
            "check": "sat_vs_censo_population_abs_diff_sum",
            "value": float((df["sat_personas"] - df["censo_personas"]).abs().sum(skipna=True)),
        },
        {
            "check": "sat_vs_censo_population_diff_rows",
            "value": int(((df["sat_personas"] - df["censo_personas"]).abs() > 0).sum()),
        },
        {
            "check": "sat_vs_censo_nbi_persons_abs_diff_sum",
            "value": float(
                (df["sat_personas"] - df["censo_nbi_personas_viviendas_particulares"]).abs().sum(skipna=True)
            ),
        },
        {
            "check": "sat_vs_censo_nbi_persons_diff_rows",
            "value": int(
                ((df["sat_personas"] - df["censo_nbi_personas_viviendas_particulares"]).abs() > 0).sum()
            ),
        },
        {
            "check": "sat_vs_censo_nbi_poor_abs_diff_sum",
            "value": float((df["sat_pobres"] - df["censo_nbi_pobres"]).abs().sum(skipna=True)),
        },
        {
            "check": "sat_vs_censo_nbi_poor_diff_rows",
            "value": int(((df["sat_pobres"] - df["censo_nbi_pobres"]).abs() > 0).sum()),
        },
    ]
    report_df = pd.concat([pd.DataFrame(report), crosswalk_report], ignore_index=True)
    return df, report_df, build_issue_report(df)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--satellite", type=Path, default=ROOT / "data" / "datos22.xlsx")
    parser.add_argument("--census-db", type=Path, default=DEFAULT_CENSUS_DB)
    parser.add_argument("--census-indicators", type=Path, default=DEFAULT_OUT_DIR / "census_indicator_features.csv")
    parser.add_argument("--include-census-indicators", action="store_true")
    parser.add_argument("--adm3", type=Path, default=ROOT / "data" / "ecu_adm_2024" / "ecu_adm_adm3_2024.shp")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    dataset, report, issues = build_dataset(args)
    suffix = "_full_census" if args.include_census_indicators else ""
    dataset.to_csv(args.out_dir / f"parroquia_features{suffix}.csv", index=False, encoding="utf-8")
    report.to_csv(args.out_dir / f"merge_report{suffix}.csv", index=False, encoding="utf-8")
    issues.to_csv(args.out_dir / f"merge_issues{suffix}.csv", index=False, encoding="utf-8")
    print(report.to_csv(index=False), end="")
    print(f"\nDataset: {args.out_dir / f'parroquia_features{suffix}.csv'}")
    print(f"Reporte: {args.out_dir / f'merge_report{suffix}.csv'}")
    print(f"Issues: {args.out_dir / f'merge_issues{suffix}.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
