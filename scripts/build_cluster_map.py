"""Choropleth map of the national K-Means (k=5, Political Compass) parish clustering.

Joins data/model/parroquia_clusters_pc_kmeans_k5.csv (the main clustering result,
paper section 6) to the ADM3 parish boundaries via ADM3_PCODE, and renders a
categorical choropleth using a colorblind-validated 5-hue palette (dataviz skill,
validated with scripts/validate_palette.js: blue/yellow/aqua/violet/red, all-pairs
PASS on normal vision, WARN on CVD 6-8 band -> mitigated here with a visible white
stroke between polygons, per the skill's "gaps" secondary-encoding option).

Output: papers/01_nacional_territorio_ideologia/figures/mapa_clusters_nacional.png
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ADM3 = ROOT / "data" / "ecu_adm_2024" / "ecu_adm_adm3_2024.shp"
CLUSTERS = ROOT / "data" / "model" / "parroquia_clusters_pc_kmeans_k5.csv"
OUT_DIR = ROOT / "papers" / "01_nacional_territorio_ideologia" / "figures"

# Validated palette (dataviz skill): blue, yellow, aqua, violet, red.
# All-pairs PASS (normal-vision floor, worst pair dE 16.3) on --pairs all,
# CVD in the legal-with-secondary-encoding 6-8 band -> white polygon stroke below.
CLUSTER_COLORS = {
    0: "#2a78d6",  # blue
    1: "#eda100",  # yellow
    2: "#1baf7a",  # aqua
    3: "#4a3aa7",  # violet
    4: "#e34948",  # red
}

# Short profile tag per cluster, matching paper section 6's table (n, direction).
CLUSTER_LABELS = {
    0: "Outliers urbanos",
    1: "Intermedio (mayor pobreza)",
    2: "Mayor integración urbana/económica",
    3: "Mayor vulnerabilidad socioeconómica",
    4: "Intermedio",
}


def _plot_clusters(ax, gdf) -> None:
    no_cluster = gdf[gdf["cluster"].isna()]
    if len(no_cluster):
        no_cluster.plot(ax=ax, color="#e1e0d9", edgecolor="white", linewidth=0.15)
    for cluster_id, color in CLUSTER_COLORS.items():
        subset = gdf[gdf["cluster"] == cluster_id]
        if len(subset):
            subset.plot(ax=ax, color=color, edgecolor="white", linewidth=0.15)
    ax.set_axis_off()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    adm3 = gpd.read_file(ADM3)[["ADM3_PCODE", "ADM1_ES", "geometry"]]
    clusters = pd.read_csv(CLUSTERS)[["ADM3_PCODE", "cluster"]]

    merged = adm3.merge(clusters, on="ADM3_PCODE", how="left")
    matched = merged["cluster"].notna().sum()
    print(f"Parroquias con geometría + cluster: {matched} / {len(merged)} (shapefile); {len(clusters)} en el CSV de clusters")

    is_galapagos = merged["ADM1_ES"].str.contains("Gal", na=False)
    mainland, galapagos = merged[~is_galapagos], merged[is_galapagos]

    fig = plt.figure(figsize=(10, 9.3), dpi=200)
    ax_main = fig.add_axes([0.32, 0.03, 0.66, 0.90])
    ax_gal = fig.add_axes([0.04, 0.05, 0.24, 0.17])

    _plot_clusters(ax_main, mainland)
    _plot_clusters(ax_gal, galapagos)
    ax_gal.set_title("Galápagos", fontsize=8, color="#52514e", pad=2)

    fig.suptitle(
        "Tipología territorial parroquial — K-Means k=5, censo + satelital + Political Compass",
        fontsize=12,
        color="#0b0b0b",
        y=0.985,
    )

    no_cluster = merged[merged["cluster"].isna()]
    handles = [
        plt.Line2D([0], [0], marker="s", linestyle="", markersize=10, markerfacecolor=c, markeredgecolor="none")
        for c in CLUSTER_COLORS.values()
    ]
    labels = [f"{cid} — {CLUSTER_LABELS[cid]} (n={(merged['cluster'] == cid).sum()})" for cid in CLUSTER_COLORS]
    if len(no_cluster):
        handles.append(plt.Line2D([0], [0], marker="s", linestyle="", markersize=10, markerfacecolor="#e1e0d9", markeredgecolor="none"))
        labels.append(f"Sin resultado electoral agregado (n={len(no_cluster)})")

    fig.legend(
        handles,
        labels,
        loc="lower left",
        bbox_to_anchor=(0.03, 0.30),
        fontsize=8.5,
        frameon=False,
        title="Cluster",
        title_fontsize=9.5,
    )
    fig.text(
        0.03, 0.005,
        "Fuente: elaboración propia — INEC 2022, CNE 2025, VIIRS/NDVI/MNDWI.\n"
        "Cartografía ADM3: HDX COD-AB Ecuador (fuente INEC).",
        fontsize=6.5,
        color="#898781",
    )

    out_path = OUT_DIR / "mapa_clusters_nacional.png"
    fig.savefig(out_path, dpi=200, facecolor="white")
    print(f"Guardado: {out_path}")


if __name__ == "__main__":
    main()
