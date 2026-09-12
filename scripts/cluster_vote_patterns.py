"""Cluster parishes using non-electoral features and summarize vote patterns."""

from __future__ import annotations

import argparse
import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")
warnings.filterwarnings("ignore", message="Could not find the number of physical cores.*")

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, DBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "model" / "parroquia_features.csv"
DEFAULT_OUT_DIR = ROOT / "data" / "model"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


BASE_FEATURES = [
    "viirs",
    "m2_auo",
    "edi",
    "crts",
    "dt",
    "ct",
    "edu",
    "ndvi",
    "mndwi",
    "area",
    "sat_pobreza_pct",
    "censo_hombres_pct",
    "censo_mujeres_pct",
    "censo_nbi_pobreza_pct",
]

PC_CLASS_COLUMNS = {
    "pc_centro": [
        "elec_v1_centro",
        "elec_v1_centro_con_tinte_institucionalista",
        "elec_v1_centro_pragmatico",
    ],
    "pc_centro_derecha": [
        "elec_v1_centro_derecha_moderado",
    ],
    "pc_centro_izquierda": [
        "elec_v1_centro_izquierda_libertaria",
    ],
    "pc_derecha_liberal": [
        "elec_v1_derecha_liberal",
        "elec_v1_daniel_noboa_azin_derecha_liberal_moderada",
    ],
    "pc_derecha_autoritaria": [
        "elec_v1_derecha_autoritaria",
        "elec_v1_derecha_autoritaria_dura",
        "elec_v1_derecha_autoritaria_moderada",
        "elec_v1_derecha_moderada",
    ],
    "pc_izquierda_autoritaria": [
        "elec_v1_izquierda_autoritaria",
        "elec_v1_luisa_gonzalez_izquierda_autoritaria",
    ],
    "pc_izquierda_libertaria": [
        "elec_v1_izquierda_libertaria",
    ],
}

PC_SUMMARY_COLUMNS = [
    "pc_centro",
    "pc_centro_derecha",
    "pc_centro_izquierda",
    "pc_derecha_liberal",
    "pc_derecha_autoritaria",
    "pc_izquierda_autoritaria",
    "pc_izquierda_libertaria",
    "pc_derecha_total",
    "pc_izquierda_total",
    "pc_liberal_total",
    "pc_autoritaria_total",
    "pc_economic_right_minus_left",
    "pc_social_authoritarian_minus_libertarian",
]


def numeric_columns(df: pd.DataFrame, prefixes: tuple[str, ...]) -> list[str]:
    return [
        col
        for col in df.columns
        if col.startswith(prefixes) and pd.api.types.is_numeric_dtype(df[col])
    ]


def add_political_compass_features(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    for new_col, source_cols in PC_CLASS_COLUMNS.items():
        available = [col for col in source_cols if col in work.columns]
        work[new_col] = work[available].sum(axis=1, min_count=1) if available else np.nan

    work["pc_derecha_total"] = work[["pc_centro_derecha", "pc_derecha_liberal", "pc_derecha_autoritaria"]].sum(
        axis=1, min_count=1
    )
    work["pc_izquierda_total"] = work[["pc_centro_izquierda", "pc_izquierda_autoritaria", "pc_izquierda_libertaria"]].sum(
        axis=1, min_count=1
    )
    work["pc_liberal_total"] = work[["pc_derecha_liberal", "pc_izquierda_libertaria", "pc_centro_izquierda"]].sum(
        axis=1, min_count=1
    )
    work["pc_autoritaria_total"] = work[["pc_derecha_autoritaria", "pc_izquierda_autoritaria"]].sum(axis=1, min_count=1)
    work["pc_economic_right_minus_left"] = work["pc_derecha_total"] - work["pc_izquierda_total"]
    work["pc_social_authoritarian_minus_libertarian"] = work["pc_autoritaria_total"] - work["pc_liberal_total"]
    return work


def build_features(df: pd.DataFrame, include_election_features: bool) -> tuple[pd.DataFrame, list[str]]:
    df = add_political_compass_features(df)
    features = [col for col in BASE_FEATURES if col in df.columns]
    features.extend(numeric_columns(df, ("censo_edad_",)))
    features.extend(numeric_columns(df, ("censo_ind_",)))
    features.extend(numeric_columns(df, ("censo_rate_",)))

    work = df.copy()
    for col in ("sat_personas", "censo_personas", "censo_nbi_personas_viviendas_particulares"):
        if col in work.columns:
            new_col = f"log_{col}"
            work[new_col] = np.log1p(work[col])
            features.append(new_col)

    if include_election_features:
        features.extend([col for col in PC_SUMMARY_COLUMNS if col in work.columns])

    features = sorted(dict.fromkeys(features))
    return work, features


def transformed_features(df: pd.DataFrame, features: list[str], pca_variance: float | None = None) -> np.ndarray:
    X = df[features]
    steps = [
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ]
    if pca_variance is not None:
        steps.append(("pca", PCA(n_components=pca_variance, random_state=42)))
    pipeline = Pipeline(steps)
    return pipeline.fit_transform(X)


def cluster_labels(X: np.ndarray, method: str, k: int, random_state: int, eps: float, min_samples: int) -> np.ndarray:
    if method == "kmeans":
        return KMeans(n_clusters=k, n_init=25, random_state=random_state).fit_predict(X)
    if method == "gmm":
        return GaussianMixture(n_components=k, covariance_type="full", random_state=random_state).fit_predict(X)
    if method == "agglomerative":
        return AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(X)
    if method == "dbscan":
        return DBSCAN(eps=eps, min_samples=min_samples).fit_predict(X)
    raise ValueError(f"Metodo no soportado: {method}")


def score_labels(X: np.ndarray, labels: np.ndarray) -> dict[str, float | int | None]:
    non_noise = labels != -1
    clusters = sorted(set(labels[non_noise]))
    out: dict[str, float | int | None] = {
        "clusters": len(clusters),
        "noise_points": int((labels == -1).sum()),
        "silhouette": None,
        "calinski_harabasz": None,
        "davies_bouldin": None,
    }
    if len(clusters) < 2 or non_noise.sum() <= len(clusters):
        return out

    X_score = X[non_noise]
    y_score = labels[non_noise]
    out["silhouette"] = float(silhouette_score(X_score, y_score))
    out["calinski_harabasz"] = float(calinski_harabasz_score(X_score, y_score))
    out["davies_bouldin"] = float(davies_bouldin_score(X_score, y_score))
    return out


def run_clustering(
    df: pd.DataFrame,
    features: list[str],
    method: str,
    k: int,
    random_state: int,
    eps: float,
    min_samples: int,
    pca_variance: float | None,
) -> tuple[pd.Series, dict[str, float | int | None]]:
    X = transformed_features(df, features, pca_variance=pca_variance)
    labels = cluster_labels(X, method, k, random_state, eps, min_samples)
    scores = score_labels(X, labels)
    return pd.Series(labels, index=df.index, name="cluster"), scores


def summarize_clusters(df: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    vote_cols = [
        col
        for col in PC_SUMMARY_COLUMNS
        + [
            "elec_v2_nulos_pct",
            "elec_v2_blancos_pct",
            "sat_pobreza_pct",
            "censo_nbi_pobreza_pct",
            "viirs",
            "ndvi",
            "mndwi",
        ]
        if col in df.columns
    ]
    summary = (
        df.groupby("cluster")
        .agg(
            parroquias=("ADM3_PCODE", "count"),
            parroquias_con_voto_pc=("pc_economic_right_minus_left", "count"),
            provincia_mas_comun=("provincia_sat", lambda s: s.mode().iat[0] if not s.mode().empty else None),
            canton_mas_comun=("canton_sat", lambda s: s.mode().iat[0] if not s.mode().empty else None),
            **{col: (col, "mean") for col in vote_cols},
        )
        .reset_index()
        .sort_values("pc_economic_right_minus_left", ascending=False)
    )

    feature_means = df.groupby("cluster")[features].mean()
    overall = df[features].mean()
    std = df[features].std().replace(0, np.nan)
    profile = ((feature_means - overall) / std).reset_index()
    profile = profile.melt(id_vars="cluster", var_name="feature", value_name="z_vs_promedio")
    profile = profile.sort_values(["cluster", "z_vs_promedio"], ascending=[True, False])
    return summary, profile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--method",
        choices=("kmeans", "gmm", "agglomerative", "dbscan"),
        default="kmeans",
    )
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument("--eps", type=float, default=3.0)
    parser.add_argument("--min-samples", type=int, default=10)
    parser.add_argument("--pca-variance", type=float)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--include-election-features", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    df = pd.read_csv(args.input)
    df, features = build_features(df, args.include_election_features)
    df["cluster"], scores = run_clustering(
        df,
        features,
        method=args.method,
        k=args.k,
        random_state=args.random_state,
        eps=args.eps,
        min_samples=args.min_samples,
        pca_variance=args.pca_variance,
    )
    summary, profile = summarize_clusters(df, features)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "pc" if args.include_election_features else "socio"
    if args.input.stem != "parroquia_features":
        suffix = f"{suffix}_{args.input.stem.replace('parroquia_features_', '')}"
    run_name = f"{suffix}_{args.method}"
    if args.pca_variance is not None:
        run_name = f"{run_name}_pca{str(args.pca_variance).replace('.', 'p')}"
    if args.method == "dbscan":
        run_name = f"{run_name}_eps{str(args.eps).replace('.', 'p')}_min{args.min_samples}"
    else:
        run_name = f"{run_name}_k{args.k}"
    clusters_path = args.out_dir / f"parroquia_clusters_{run_name}.csv"
    summary_path = args.out_dir / f"cluster_summary_{run_name}.csv"
    profile_path = args.out_dir / f"cluster_feature_profile_{run_name}.csv"
    df.to_csv(clusters_path, index=False, encoding="utf-8")
    summary.to_csv(summary_path, index=False, encoding="utf-8")
    profile.to_csv(profile_path, index=False, encoding="utf-8")

    print(f"method,{args.method}")
    print(f"features,{len(features)}")
    print(f"k,{args.k}")
    print(f"clusters_found,{scores['clusters']}")
    print(f"noise_points,{scores['noise_points']}")
    for metric in ("silhouette", "calinski_harabasz", "davies_bouldin"):
        if scores[metric] is not None:
            print(f"{metric},{scores[metric]:.4f}")
    print(f"clusters,{clusters_path}")
    print(f"summary,{summary_path}")
    print(f"profile,{profile_path}")
    print()
    print(summary.to_csv(index=False), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
