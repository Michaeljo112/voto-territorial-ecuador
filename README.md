# Territorio, condiciones socioeconómicas y preferencias ideológicas a nivel parroquial en Ecuador

Repositorio de datos y código reproducible para estudiar patrones territoriales de voto en Ecuador a nivel de parroquia (n=1.041), integrando datos satelitales, censales (INEC 2022) y electorales (primera vuelta presidencial 2025, reclasificada con una taxonomía tipo Political Compass).

## Estructura

```
docs/           — documentación técnica extendida del pipeline
notebooks/      — clasificación electoral + Political Compass, de microdato CNE crudo a CSV agregado por parroquia
scripts/        — pipeline de construcción de la base censal, matriz de modelado, clustering y mapa de clusters
config/         — manifiesto de tabulados INEC usado por scripts/build_inec_censo_db.py
data/           — datos fuente (pequeños) y salidas curadas/derivadas del pipeline; ver data/README.md
```

## Cómo reproducir

```bash
pip install -r requirements.txt
```

Ver [data/README.md](data/README.md) para el pipeline completo paso a paso, qué datos ya están incluidos y cómo regenerar lo que no se versiona por tamaño (base censal INEC completa, ~1GB; cartografía ADM3, ~230MB).

## Datos

Este repositorio integra tres fuentes públicas:

- **Satelital/socioeconómica** — VIIRS (luz nocturna), NDVI, MNDWI por parroquia.
- **Censal** — tabulados oficiales del [INEC](https://www.ecuadorencifras.gob.ec/), Censo de Población y Vivienda 2022.
- **Electoral** — resultados oficiales del [CNE](https://www.cne.gob.ec/), primera vuelta presidencial 2025, reclasificados mediante un codebook ideológico propio (ver `scripts/cluster_vote_patterns.py`, `PC_CLASS_COLUMNS`, y el codebook fuente en `data/PiliticalCompass.xlsx`).

Ver [data/README.md](data/README.md) para procedencia detallada de cada archivo y licencia/términos de cada fuente.

## Licencia

El código (scripts, notebooks) se distribuye bajo licencia MIT — ver [LICENSE](LICENSE). Los datos redistribuidos en `data/` provienen de fuentes públicas de gobierno (INEC, CNE); revisar sus términos de uso antes de reutilizar o redistribuir.
