# Datos — procedencia y cómo regenerar lo que no está versionado

## Qué sí está en este repositorio

| Archivo | Qué es | Fuente |
|---|---|---|
| `datos22.xlsx` | Variables satelitales (VIIRS, NDVI, MNDWI) y socioeconómicas por parroquia | Google Earth Engine, pipeline propio (ver [Estimando-la-pobreza-parroquial](https://github.com/Michaeljo112/Estimando-la-pobreza-parroquial)) |
| `diccionario_parroquias.xlsx` | Cruce CODPRO/CODCAN/CODPAR → `ADM3_PCODE` | Elaboración propia sobre codificación INEC/CNE |
| `PiliticalCompass.xlsx` | Codebook de clasificación ideológica de los 16 binomios de primera vuelta 2025 — un eje económico y uno social por candidatura, mapeados a 7 categorías agregadas en `scripts/cluster_vote_patterns.py` (`PC_CLASS_COLUMNS`) | Codificación propia (un solo analista, sin verificación inter-codificador) |
| `Primera-Vuelta.sav`, `Segunda-Vuelta.sav` | Microdato crudo de resultados electorales por junta, primera y segunda vuelta presidencial 2025 | [CNE — Consejo Nacional Electoral](https://www.cne.gob.ec/), datos públicos |
| `Organizaciones-Politicas.sav`, `parroquias.sav` | Catálogos auxiliares del CNE (organizaciones políticas, parroquias) | CNE |
| `1era.csv`, `2da.csv`, `1raF.csv`, `1raM.csv`, `2daF.csv`, `2daM.csv` | Resultados agregados a nivel de parroquia (total y por sexo de junta), ya reclasificados con el codebook Political Compass | Generado desde los `.sav` de arriba por los notebooks en `notebooks/` |
| `model/*.csv` | Salidas curadas y derivadas del pipeline (matriz de modelado, clusters, comparación de métodos, catálogo censal completo normalizado) | Generadas por los scripts en `scripts/`, ver tabla abajo |

## Qué NO está versionado (demasiado grande o regenerable) y cómo obtenerlo

### 1. Base censal INEC 2022 tabulada (`data/censo_inec/`)

No se versiona: el `.sqlite` resultante pesa ~1 GB. Se regenera descargando directo del INEC:

```bash
python scripts/build_inec_censo_db.py
```

Usa el manifiesto `config/inec_censo_2022_tabulados.csv` (sí versionado) para descargar y ensamblar los tabulados oficiales. Luego:

```bash
python scripts/validate_inec_population_totals.py   # reproduce 2,032 checks, 0 fallos (ver paper, sección 3.1)
python scripts/build_census_indicator_features.py    # -> data/model/census_indicator_features.csv (ya incluido)
```

### 2. Cartografía administrativa ADM3 (`data/ecu_adm_2024/`)

No se versiona: el shapefile ADM3 pesa ~230 MB (excede el límite de 100 MB de GitHub). Es la cartografía estándar **COD-AB** (Common Operational Dataset – Administrative Boundaries) para Ecuador, con codificación `PCODE`, nivel ADM0-ADM3 (1.044 features en ADM3), fuente INEC, geoservicios y vetting de ITOS/USAID. Confirmado en HDX: **[data.humdata.org/dataset/cod-ab-ecu](https://data.humdata.org/dataset/cod-ab-ecu)** — descargar el shapefile ADM3 (`ecu_admbnda_adm3_*`) desde esa página y renombrar/colocar como `data/ecu_adm_2024/ecu_adm_adm3_2024.*`.

Colocar los archivos `ecu_adm_adm3_2024.*` en `data/ecu_adm_2024/` antes de correr:

```bash
python scripts/build_parish_model_dataset.py
```

(Este paso no es necesario para reproducir el análisis principal — `data/model/parroquia_features.csv` ya está incluido. Solo hace falta si quieres regenerar la matriz desde cero.)

Para regenerar el mapa de clusters (choropleth parroquial nacional con inset de Galápagos) sí hace falta este shapefile:

```bash
python scripts/build_cluster_map.py
```

### 3. Notebooks → CSVs electorales agregados

`notebooks/PrimeraVuelta.ipynb`, `SegundaVuelta.ipynb` (y variantes `_porSexo`) toman los `.sav` crudos + `PiliticalCompass.xlsx` y producen `1era.csv`/`2da.csv`/etc. — ya incluidos, pero los notebooks se incluyen para que ese paso también sea auditable/re-ejecutable.

## Pipeline completo (orden)

```bash
pip install -r requirements.txt

# 1. Clasificación electoral + Political Compass (ya materializado en data/*.csv; re-ejecutar notebooks si se edita el codebook)
jupyter nbconvert --to notebook --execute notebooks/PrimeraVuelta.ipynb

# 2. Base censal INEC (pesado, ~1GB, descarga de internet)
python scripts/build_inec_censo_db.py
python scripts/validate_inec_population_totals.py

# 3. Matriz de modelado parroquial (requiere ecu_adm_2024/, ver sección 2 arriba)
python scripts/build_parish_model_dataset.py

# 4. Catálogo censal completo (667 tasas, robustez sección 8 del paper)
python scripts/build_census_indicator_features.py
python scripts/normalize_census_indicators.py

# 5. Clustering principal y comparación de métodos
# IMPORTANTE: la flag --include-election-features es necesaria para reproducir
# las cifras exactas del paper (silhouette 0.152 en k=5, tabla de la sección 5.1,
# y los tamaños de cluster 301/6/256/132/346 de la sección 6). Sin la flag,
# el script usa 35 variables en vez de 48 y da resultados distintos (verificado
# 2026-09-10 al auditar el paper contra los datos: el CSV de comparación de
# métodos que estaba en este repo antes de esa fecha era de una corrida sin
# esta flag, con un conteo de features inconsistente — ya corregido).
python scripts/cluster_vote_patterns.py --k 5 --include-election-features
python scripts/compare_clustering_methods.py --include-election-features

# 6. Robustez con catálogo censal completo (sección 8 del paper: 667 tasas,
#    PCA 90% varianza → 83 componentes, silhouette 0.087 sin PCA → 0.100 con PCA)
python scripts/build_parish_model_dataset.py \
  --include-census-indicators \
  --census-indicators data/model/census_indicator_features_normalized.csv
# El script nombra la salida "parroquia_features_full_census.csv" (sin "_normalized");
# renombrar para que coincida con lo que usan los pasos siguientes y con lo ya
# incluido en este repo:
mv data/model/parroquia_features_full_census.csv data/model/parroquia_features_full_census_normalized.csv
mv data/model/merge_report_full_census.csv data/model/merge_report_full_census_normalized.csv
mv data/model/merge_issues_full_census.csv data/model/merge_issues_full_census_normalized.csv

python scripts/compare_clustering_methods.py \
  --input data/model/parroquia_features_full_census_normalized.csv --include-election-features
python scripts/compare_clustering_methods.py \
  --input data/model/parroquia_features_full_census_normalized.csv --include-election-features --pca-variance 0.9
python scripts/cluster_vote_patterns.py \
  --input data/model/parroquia_features_full_census_normalized.csv --include-election-features --k 5 --pca-variance 0.9
# -> cluster_summary_pc_full_census_normalized_kmeans_pca0p9_k5.csv (tabla sección 8)

# 7. Figura 1 (mapa de clusters, requiere ecu_adm_2024/, ver sección 2 arriba)
python scripts/build_cluster_map.py
```

Todas las salidas de los pasos 3-7 ya están incluidas en `data/model/` y `papers/01_nacional_territorio_ideologia/figures/` — no hace falta re-ejecutar nada para verificar las tablas ni la figura del paper, solo para regenerar desde la fuente cruda.

**Verificado reproducible end-to-end el 2026-09-11:** se corrieron los pasos 5, 6 y 7 desde cero (incluida la descarga/consulta del censo INEC crudo) y las salidas coincidieron exactamente (`git diff` vacío) con lo ya versionado en este repositorio, y con cada cifra citada en el draft del paper (secciones 3.1, 5.1, 6 y 8).
