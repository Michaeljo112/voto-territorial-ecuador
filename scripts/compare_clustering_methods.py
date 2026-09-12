"""Compare clustering methods on the parish modeling dataset."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

from cluster_vote_patterns import (
    DEFAULT_INPUT,
    DEFAULT_OUT_DIR,
    build_features,
    cluster_labels,
    score_labels,
    transformed_features,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


METHOD_RUNS = [
    {"method": "kmeans", "k": 4},
    {"method": "kmeans", "k": 5},
    {"method": "kmeans", "k": 6},
    {"method": "kmeans", "k": 7},
    {"method": "kmeans", "k": 8},
    {"method": "gmm", "k": 4},
    {"method": "gmm", "k": 5},
    {"method": "gmm", "k": 6},
    {"method": "gmm", "k": 7},
    {"method": "gmm", "k": 8},
    {"method": "agglomerative", "k": 4},
    {"method": "agglomerative", "k": 5},
    {"method": "agglomerative", "k": 6},
    {"method": "agglomerative", "k": 7},
    {"method": "agglomerative", "k": 8},
    {"method": "dbscan", "eps": 2.0, "min_samples": 10},
    {"method": "dbscan", "eps": 2.5, "min_samples": 10},
    {"method": "dbscan", "eps": 3.0, "min_samples": 10},
    {"method": "dbscan", "eps": 3.5, "min_samples": 10},
    {"method": "dbscan", "eps": 4.0, "min_samples": 10},
]


def compare(args: argparse.Namespace) -> pd.DataFrame:
    df = pd.read_csv(args.input)
    df, features = build_features(df, args.include_election_features)
    X = transformed_features(df, features, pca_variance=args.pca_variance)

    rows = []
    for spec in METHOD_RUNS:
        method = spec["method"]
        k = int(spec.get("k", args.k))
        eps = float(spec.get("eps", args.eps))
        min_samples = int(spec.get("min_samples", args.min_samples))
        labels = cluster_labels(X, method, k, args.random_state, eps, min_samples)
        scores = score_labels(X, labels)
        counts = pd.Series(labels).value_counts().to_dict()
        cluster_sizes = [int(counts[label]) for label in sorted(counts) if label != -1]
        rows.append(
            {
                "feature_set": "pc" if args.include_election_features else "socio",
                "method": method,
                "k": k if method != "dbscan" else None,
                "eps": eps if method == "dbscan" else None,
                "min_samples": min_samples if method == "dbscan" else None,
                "features": len(features),
                "pca_variance": args.pca_variance,
                "transformed_features": X.shape[1],
                "clusters_found": scores["clusters"],
                "noise_points": scores["noise_points"],
                "silhouette": scores["silhouette"],
                "calinski_harabasz": scores["calinski_harabasz"],
                "davies_bouldin": scores["davies_bouldin"],
                "min_cluster_size": min(cluster_sizes) if cluster_sizes else None,
                "max_cluster_size": max(cluster_sizes) if cluster_sizes else None,
            }
        )
    return pd.DataFrame(rows).sort_values(["silhouette", "davies_bouldin"], ascending=[False, True])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--include-election-features", action="store_true")
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument("--eps", type=float, default=3.0)
    parser.add_argument("--min-samples", type=int, default=10)
    parser.add_argument("--pca-variance", type=float)
    parser.add_argument("--random-state", type=int, default=42)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result = compare(args)
    suffix = "pc" if args.include_election_features else "socio"
    if args.input.stem != "parroquia_features":
        suffix = f"{suffix}_{args.input.stem.replace('parroquia_features_', '')}"
    if args.pca_variance is not None:
        suffix = f"{suffix}_pca{str(args.pca_variance).replace('.', 'p')}"
    out_path = args.out_dir / f"clustering_method_comparison_{suffix}.csv"
    result.to_csv(out_path, index=False, encoding="utf-8")
    print(f"comparison,{out_path}")
    print(result.to_csv(index=False), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
