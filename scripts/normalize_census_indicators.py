"""Convert raw INEC census indicator counts into within-table shares (rates).

`build_census_indicator_features.py` produces one raw count per (table, dimension,
category) cell -- e.g. "numero de hogares con 1 miembro", "numero total de hogares".
Feeding those raw counts directly into clustering lets parish population size
dominate the distance metric, since most of the 1,057 columns are highly
correlated proxies for "how big is this parish".

This script instead expresses each category count as a share of the closest
enclosing "total" row from the same census table, using the pipe-delimited
breadcrumb encoded in the `metric` column of the indicator dictionary
(e.g. "Tipo de vivienda | Viviendas particulares | Desocupada" is normalized by
"Tipo de vivienda | Viviendas particulares | Total viviendas particulares", the
most specific enclosing total; a flat category like "Numero de miembros del
hogar | 1 persona" falls back to the table-level total, "Numero total de
hogares").

Rows whose (slug, table_number, dimension_4, dimension_5) group has no
"total"-labeled sibling at all cannot be normalized this way and are excluded
from the rate matrix (documented in the report CSV) rather than guessed at.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "data" / "model"
DEFAULT_FEATURES = DEFAULT_OUT_DIR / "census_indicator_features.csv"
DEFAULT_DICTIONARY = DEFAULT_OUT_DIR / "census_indicator_dictionary.csv"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

GROUP_KEY = ["slug", "table_number", "dim4", "dim5"]


def _segments(metric: object) -> list[str]:
    return [s.strip() for s in str(metric).split("|")]


def _is_total_segment(segment: str) -> bool:
    return "total" in segment.lower()


def build_denominator_map(dictionary: pd.DataFrame) -> tuple[dict[str, str], pd.DataFrame]:
    """Map each non-total feature_id to its closest enclosing total feature_id.

    Returns (numerator -> denominator map, dataframe of rows that could not be
    matched with the reason why).
    """
    d = dictionary.copy()
    d["dim4"] = d["dimension_4"].fillna("")
    d["dim5"] = d["dimension_5"].fillna("")
    d["segs"] = d["metric"].map(_segments)
    d["is_total"] = d["segs"].map(lambda s: _is_total_segment(s[-1]))
    d["path"] = d["segs"].map(lambda s: tuple(s[:-1]))

    denom_map: dict[str, str] = {}
    excluded_rows: list[dict[str, str]] = []

    for _, group in d.groupby(GROUP_KEY, dropna=False):
        totals = group[group["is_total"]]
        if totals.empty:
            for _, row in group.iterrows():
                excluded_rows.append(
                    {
                        "feature_id": row["feature_id"],
                        "metric": row["metric"],
                        "reason": "no_total_row_in_table_group",
                    }
                )
            continue
        for _, row in group.iterrows():
            if row["is_total"]:
                continue
            candidates = totals[totals["path"].map(lambda tp: row["path"][: len(tp)] == tp)]
            if candidates.empty:
                excluded_rows.append(
                    {
                        "feature_id": row["feature_id"],
                        "metric": row["metric"],
                        "reason": "no_matching_total_prefix",
                    }
                )
                continue
            best = candidates.loc[candidates["path"].map(len).idxmax()]
            denom_map[row["feature_id"]] = best["feature_id"]

    excluded = pd.DataFrame(excluded_rows, columns=["feature_id", "metric", "reason"])
    return denom_map, excluded


def build_rate_matrix(
    wide: pd.DataFrame, dictionary: pd.DataFrame, denom_map: dict[str, str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rate_cols = {}
    rate_dict_rows = []
    dict_by_id = dictionary.set_index("feature_id")
    for numer_id, denom_id in denom_map.items():
        if numer_id not in wide.columns or denom_id not in wide.columns:
            continue
        denom = wide[denom_id]
        rate = wide[numer_id] / denom.replace(0, np.nan)
        rate_col = f"censo_rate_{numer_id[len('censo_ind_'):]}"
        rate_cols[rate_col] = rate
        rate_dict_rows.append(
            {
                "rate_feature_id": rate_col,
                "numerator_feature_id": numer_id,
                "denominator_feature_id": denom_id,
                "numerator_metric": dict_by_id.loc[numer_id, "metric"] if numer_id in dict_by_id.index else None,
                "denominator_metric": dict_by_id.loc[denom_id, "metric"] if denom_id in dict_by_id.index else None,
                "table_name": dict_by_id.loc[numer_id, "table_name"] if numer_id in dict_by_id.index else None,
            }
        )
    rates = pd.DataFrame(rate_cols, index=wide.index)
    rates.insert(0, "ADM3_PCODE", wide["ADM3_PCODE"])
    rate_dictionary = pd.DataFrame(rate_dict_rows)
    return rates, rate_dictionary


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    wide = pd.read_csv(args.features)
    dictionary = pd.read_csv(args.dictionary)

    denom_map, excluded = build_denominator_map(dictionary)
    rates, rate_dictionary = build_rate_matrix(wide, dictionary, denom_map)

    out_of_range = {
        col: int(((rates[col] < -0.001) | (rates[col] > 1.5)).sum())
        for col in rates.columns
        if col != "ADM3_PCODE"
    }
    n_out_of_range_cols = sum(1 for v in out_of_range.values() if v > 0)

    report = pd.DataFrame(
        [
            {"check": "raw_indicator_columns", "value": len(dictionary)},
            {"check": "rate_columns_built", "value": rate_dictionary.shape[0]},
            {"check": "excluded_columns_no_total", "value": excluded["feature_id"].nunique() if not excluded.empty else 0},
            {"check": "distinct_denominator_columns_used", "value": len(set(denom_map.values()))},
            {"check": "rate_columns_with_any_value_outside_0_1_5pct", "value": n_out_of_range_cols},
        ]
    )

    rates_path = args.out_dir / "census_indicator_features_normalized.csv"
    dict_path = args.out_dir / "census_indicator_dictionary_normalized.csv"
    excluded_path = args.out_dir / "census_indicator_excluded_raw.csv"
    report_path = args.out_dir / "census_indicator_normalization_report.csv"

    rates.to_csv(rates_path, index=False, encoding="utf-8")
    rate_dictionary.to_csv(dict_path, index=False, encoding="utf-8")
    excluded.to_csv(excluded_path, index=False, encoding="utf-8")
    report.to_csv(report_path, index=False, encoding="utf-8")

    print(report.to_csv(index=False), end="")
    print(f"\nRates: {rates_path}")
    print(f"Rate dictionary: {dict_path}")
    print(f"Excluded (no reliable total): {excluded_path}")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
