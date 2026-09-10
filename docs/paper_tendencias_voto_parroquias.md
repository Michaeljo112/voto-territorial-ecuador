# Territorio, condiciones socioeconomicas y preferencias ideologicas a nivel parroquial en Ecuador

## Resumen

Este trabajo presenta un analisis exploratorio de patrones territoriales de voto en Ecuador a nivel parroquial. Integramos tres fuentes: datos satelitales y socioeconomicos parroquiales (`datos22`), tabulados censales del INEC 2022 y resultados electorales agregados del proyecto. La unidad de observacion es la parroquia, enlazada principalmente mediante `ADM3_PCODE`.

El objetivo no es predecir el voto de candidatos individuales, sino detectar agrupamientos territoriales asociados con orientaciones ideologicas aproximadas. Para ello, reclasificamos la primera vuelta electoral mediante una taxonomia tipo Political Compass y construimos ejes agregados de derecha-izquierda economica y autoritarismo-libertarismo social. El clustering principal usa K-Means con `k=5`, incluyendo variables censales, satelitales y de Political Compass.

Los resultados sugieren una estructura interpretable: parroquias con menor pobreza por NBI y mayor luminosidad nocturna tienden a concentrar mayor voto relativo en derecha liberal, mientras que parroquias con mayor pobreza por NBI tienden a concentrar mayor voto relativo en izquierda autoritaria. El resultado debe leerse como descriptivo y exploratorio, no causal.

## Pregunta de investigacion

La pregunta central es:

> Que tipos de territorios parroquiales se asocian con diferentes orientaciones ideologicas del voto?

La pregunta secundaria es metodologica:

> Que metodo de clustering ofrece una segmentacion util e interpretable para estudiar patrones territoriales de voto?

## Datos

El analisis utiliza tres familias de datos:

1. Datos satelitales y socioeconomicos parroquiales de `datos22.xlsx`, incluyendo luminosidad nocturna (`viirs`), area, indices de vegetacion/agua (`ndvi`, `mndwi`), variables construidas de infraestructura/entorno y pobreza por NBI.
2. Tabulados oficiales del Censo Ecuador 2022 del INEC, procesados desde archivos CSV publicados en la pagina de resultados censales.
3. Resultados electorales agregados a nivel parroquial, incluyendo primera vuelta, segunda vuelta y versiones por sexo de junta.

La base final contiene 1,041 parroquias. El cruce con resultados electorales cubre 1,033 parroquias; 9 parroquias no tienen resultado electoral agregado en los CSV disponibles. No hay parroquias de `datos22` sin datos censales.

## Validacion de datos censales

Antes de unir fuentes, se valido la consistencia de la poblacion censal. La tabla parroquial de estructura poblacional del INEC reproduce exactamente los totales oficiales:

- Parroquias, cantones y provincias suman el total nacional: 16,938,986 personas.
- Hombres y mujeres suman correctamente el total en cada nivel geografico.
- La validacion completa contiene 2,032 checks y 0 fallos.

Una diferencia importante aparece al comparar `datos22.Personas` con `censo_personas`: 550 parroquias difieren, con una diferencia absoluta acumulada de 54,586 personas. Esta diferencia no indica un error de union. `datos22.Personas` coincide exactamente con el tabulado INEC de pobreza por NBI para personas en viviendas particulares:

- Diferencias entre `datos22.Personas` e INEC/NBI personas en viviendas particulares: 0.
- Diferencias entre `datos22.Pobres` e INEC/NBI pobres: 0.

Por tanto, en el analisis se conservan ambas medidas: `censo_personas` como poblacion total y `sat_personas` como poblacion en viviendas particulares usada para NBI.

## Clasificacion Political Compass

La primera vuelta electoral se reclasifico en categorias ideologicas:

- Centro.
- Centro-derecha.
- Centro-izquierda.
- Derecha liberal.
- Derecha autoritaria.
- Izquierda autoritaria.
- Izquierda libertaria.

A partir de estas clases se construyeron indicadores agregados:

- `pc_derecha_total`.
- `pc_izquierda_total`.
- `pc_liberal_total`.
- `pc_autoritaria_total`.
- `pc_economic_right_minus_left`.
- `pc_social_authoritarian_minus_libertarian`.

El primer eje resume predominio relativo de derecha versus izquierda. El segundo resume predominio relativo de voto autoritario versus voto libertario. Estas medidas son aproximaciones descriptivas construidas desde una codificacion politica previa de candidaturas y no deben interpretarse como mediciones psicometricas individuales.

## Metodo

La matriz de modelado combina variables satelitales, censales y electorales ideologicas. Para el clustering principal se aplico:

1. Imputacion de valores faltantes con mediana.
2. Estandarizacion de variables con `StandardScaler`.
3. K-Means con `k=5`, `n_init=25` y semilla fija.

Se compararon tambien Gaussian Mixture Models, clustering aglomerativo y DBSCAN. DBSCAN obtuvo valores altos de silhouette en algunos parametros, pero clasifico demasiadas parroquias como ruido. Por ejemplo, con `eps=3.0` y `min_samples=10`, detecto 3 clusters y 868 parroquias como ruido. Por esa razon, se priorizo K-Means como solucion interpretable de cobertura nacional.

## Comparacion de metodos

En la especificacion con Political Compass incluido, los mejores resultados globales fueron:

| Metodo | Parametro | Clusters | Ruido | Silhouette | Davies-Bouldin |
|---|---:|---:|---:|---:|---:|
| DBSCAN | eps=3.0 | 3 | 868 | 0.294 | 1.121 |
| K-Means | k=5 | 5 | 0 | 0.152 | 1.663 |
| K-Means | k=4 | 4 | 0 | 0.152 | 1.819 |
| DBSCAN | eps=3.5 | 3 | 602 | 0.145 | 1.093 |
| K-Means | k=6 | 6 | 0 | 0.133 | 1.735 |

Aunque DBSCAN mejora la metrica silhouette, su alta proporcion de ruido reduce su utilidad para clasificar el conjunto nacional de parroquias. K-Means con `k=5` ofrece una segmentacion completa, estable e interpretable.

## Resultados

La solucion K-Means con `k=5` e inclusion de Political Compass produce los siguientes perfiles promedio:

| Cluster | Parroquias | Derecha - izquierda | Autoritario - libertario | Derecha liberal | Izquierda autoritaria | Pobreza NBI | VIIRS | NDVI |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 301 | 0.047 | -0.215 | 0.449 | 0.319 | 0.408 | 5.773 | 0.458 |
| 0 | 6 | -0.054 | 0.053 | 0.396 | 0.450 | 0.233 | 33.319 | 0.215 |
| 4 | 256 | -0.063 | -0.134 | 0.385 | 0.351 | 0.661 | 1.375 | 0.466 |
| 1 | 132 | -0.089 | -0.161 | 0.369 | 0.334 | 0.854 | 1.061 | 0.581 |
| 3 | 346 | -0.333 | 0.290 | 0.243 | 0.556 | 0.711 | 2.670 | 0.398 |

El cluster 2 agrupa 301 parroquias y muestra el mayor balance relativo hacia la derecha economica. Tiene menor pobreza NBI que la mayoria de clusters y mayor luminosidad promedio que los clusters rurales pobres. Este perfil sugiere parroquias con mayor integracion urbana o economica, donde el voto clasificado como derecha liberal tiene mayor peso.

El cluster 3 agrupa 346 parroquias y muestra el balance mas fuerte hacia la izquierda. Tambien exhibe alta pobreza por NBI y mayor peso de izquierda autoritaria. Este grupo parece capturar territorios de mayor vulnerabilidad socioeconomica donde el voto correista/estatista pesa mas.

Los clusters 1 y 4 son intermedios en el eje derecha-izquierda, pero se diferencian por pobreza, vegetacion y composicion demografica. El cluster 1 tiene pobreza NBI muy alta y mayor NDVI, lo que sugiere un perfil mas rural/amazonico o periferico. El cluster 4 tiene pobreza alta pero menor que el cluster 1 y un voto ideologico menos inclinado hacia la izquierda que el cluster 3.

El cluster 0 contiene solo 6 parroquias y debe tratarse como grupo de outliers urbanos. Su luminosidad promedio es muy superior al resto. Aunque su promedio ideologico no es el mas derechista, su pequeno tamano recomienda no sobrerrepresentarlo en la interpretacion sustantiva.

## Discusion

El patron general sugiere una relacion entre estructura territorial y orientacion del voto. La pobreza por NBI se asocia con mayor peso relativo de izquierda autoritaria, mientras que luminosidad nocturna, menor pobreza y mayor escala poblacional se asocian con mayor peso de derecha liberal. Esta relacion no debe leerse como deterministica: existen parroquias pobres con voto de derecha y parroquias urbanas con voto de izquierda. El aporte del clustering es identificar familias territoriales donde esas combinaciones son mas frecuentes.

La clasificacion Political Compass permite evitar una lectura reducida a candidatos finalistas. En segunda vuelta, el voto se comprime en dos opciones y puede ocultar afinidades ideologicas mas finas. La primera vuelta preserva una distribucion mas rica de preferencias, especialmente entre derecha liberal, derecha autoritaria, izquierda autoritaria, izquierda libertaria y centro.

## Limitaciones

Este trabajo tiene varias limitaciones importantes.

Primero, la clasificacion Political Compass es una codificacion analitica de candidaturas, no una medicion directa de preferencias individuales. Segundo, el analisis es ecologico: trabaja con parroquias, no con personas. Por tanto, no permite inferir que individuos pobres voten de determinada manera; solo describe asociaciones territoriales agregadas. Tercero, la segmentacion por K-Means presupone clusters aproximadamente esfericos en el espacio estandarizado, lo cual puede simplificar estructuras territoriales complejas. Cuarto, hay 9 parroquias sin resultados electorales agregados en la base disponible.

Ademas, algunas variables satelitales pueden capturar simultaneamente urbanizacion, actividad economica, infraestructura y densidad poblacional. La interpretacion de cada variable debe hacerse con cuidado y, preferiblemente, complementarse con mapas.

## Conclusiones

La integracion de fuentes censales, satelitales y electorales permite construir una tipologia parroquial util para estudiar tendencias de voto en Ecuador. La evidencia exploratoria apunta a una estructura territorial consistente: los espacios menos pobres y mas luminosos tienden a mostrar mayor peso relativo de derecha liberal, mientras que los espacios con mayor pobreza por NBI muestran mayor peso de izquierda autoritaria.

La solucion recomendada para esta etapa es K-Means con `k=5` e inclusion de variables Political Compass. Esta solucion sacrifica algo de separacion metrica frente a DBSCAN, pero mantiene cobertura nacional completa y produce clusters interpretables.

## Extension: clustering con el catalogo censal completo

La base `parroquia_features.csv` usada arriba incluye solo 14 variables censales curadas (edad, sexo, NBI). El INEC publica, sin embargo, 1,057 indicadores tabulados adicionales por parroquia (composicion de hogares, servicios de vivienda, TIC, migracion, discapacidad, analfabetismo, identidad de genero, etc.), extraidos por `scripts/build_census_indicator_features.py` en `data/model/census_indicator_features.csv`. Esta extension evalua si clusterizar con ese catalogo completo cambia o refuerza la estructura territorial reportada arriba.

### Normalizacion de indicadores crudos

Los 1,057 indicadores del INEC son conteos absolutos (por ejemplo "numero de hogares con 1 miembro", "numero total de hogares"), no tasas. Usarlos directamente en el clustering deja que el tamano poblacional de la parroquia domine la distancia euclidiana, incluso despues de `StandardScaler`, porque cientos de columnas terminan siendo proxies redundantes del mismo "cuan grande es la parroquia".

`scripts/normalize_census_indicators.py` convierte cada conteo en una participacion (share) dentro de su tabla censal. Cada fila del diccionario de indicadores codifica una ruta jerarquica separada por `|` (por ejemplo `Tipo de vivienda | Viviendas particulares | Desocupada`); el script busca, dentro del mismo grupo de tabla/dimension, la fila "total" mas especifica que sea prefijo de esa ruta (aqui, `Tipo de vivienda | Viviendas particulares | Total viviendas particulares`) y expresa el conteo como fraccion de ese total. Cuando no hay una fila "total" jerarquicamente compatible en el grupo, la columna se excluye de la matriz de tasas en vez de asumir un denominador arbitrario.

Resultado: 667 tasas (`censo_rate_*`) construidas sobre 1,042 parroquias, con 245 columnas "total" usadas como denominador y 46 columnas crudas excluidas por falta de un total confiable (documentadas en `data/model/census_indicator_excluded_raw.csv`). La matriz de modelado final (`data/model/parroquia_features_full_census_normalized.csv`) reemplaza los 1,057 conteos crudos por estas 667 tasas, conservando las variables satelitales, censales curadas y Political Compass ya usadas en el pipeline principal.

### Metodo y reduccion de dimensionalidad

Con las tasas del catalogo completo, la matriz de modelado pasa de ~143 a ~715 columnas (702 sin Political Compass). Esto degrada la metrica silhouette del K-Means `k=5` de 0.152 (pipeline curado) a 0.087, un efecto esperable de alta dimensionalidad y de redundancia entre indicadores (muchas tablas del INEC reportan el mismo desglose por sexo o por edad una y otra vez). Aplicando PCA reteniendo 90% de varianza (83 componentes con Political Compass, 80 sin el) antes de K-Means, el silhouette de `k=5` sube a 0.100 y el Davies-Bouldin mejora de 2.49 a 2.31.

| Metodo | k | Silhouette | Davies-Bouldin | Tamano min-max |
|---|---:|---:|---:|---|
| K-Means | 4 | 0.120 | 2.361 | 179-340 |
| GMM | 4 | 0.101 | 2.870 | 150-518 |
| K-Means | 5 | 0.100 | 2.312 | 116-311 |
| Agglomerative | 4 | 0.096 | 2.527 | 192-330 |
| K-Means | 7 | 0.095 | 2.193 | 53-264 |

`k=4` obtiene mejor silhouette que `k=5` bajo PCA, igual que en el pipeline curado. Se mantiene `k=5` como solucion principal por continuidad metodologica con el resto del paper; `k=4` queda como robustez a explorar (ver Proximos pasos). DBSCAN no encontro estructura en este espacio de alta dimensionalidad (0 clusters, toda la muestra como ruido, en los `eps` probados).

### Resultados

La solucion K-Means `k=5` con PCA (90% varianza) e inclusion de Political Compass sobre el catalogo censal completo:

| Cluster | Parroquias | Derecha - izquierda | Autoritario - libertario | Pobreza NBI | VIIRS | NDVI |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 251 | -0.010 | -0.104 | 0.333 | 7.311 | 0.424 |
| 3 | 166 | -0.082 | -0.172 | 0.515 | 2.787 | 0.476 |
| 4 | 311 | -0.138 | 0.080 | 0.670 | 2.314 | 0.467 |
| 2 | 116 | -0.174 | -0.192 | 0.815 | 1.016 | 0.451 |
| 0 | 197 | -0.254 | 0.165 | 0.915 | 1.107 | 0.456 |

El gradiente central del pipeline curado se reproduce con el catalogo completo: a medida que sube la pobreza por NBI (0.33 -> 0.52 -> 0.67 -> 0.82 -> 0.92) el eje derecha-izquierda se mueve consistentemente hacia la izquierda (-0.01 -> -0.25) y la luminosidad nocturna cae (7.3 -> 1.1). Que esta relacion sobreviva al pasar de 14 a 667 variables censales, con una matriz de modelado casi cinco veces mas grande, es evidencia adicional de que la asociacion pobreza-voto no es un artefacto de la seleccion original de variables.

Los perfiles de features (`cluster_feature_profile_pc_full_census_normalized_kmeans_pca0p9_k5.csv`) muestran que los clusters 0/1/2 se diferencian sobre todo por variables de pobreza NBI (coherente con la tabla anterior), mientras que los clusters 3/4 se diferencian principalmente por la razon de sexo de la poblacion (`censo_mujeres_pct` / `censo_hombres_pct`). Esto ultimo es en parte un artefacto de la normalizacion: muchas tablas del INEC repiten el mismo desglose "Sexo al nacer | Hombres/Mujeres" para universos distintos (educacion, discapacidad, migracion, etc.), de modo que la participacion de mujeres en la poblacion queda representada por decenas de columnas casi identicas en la matriz de 667 tasas, sobre-ponderando ese eje frente a otros. Ver limitacion abajo.

### Limitaciones especificas de esta extension

- 46 indicadores crudos (de 1,057) no tienen una fila "total" jerarquicamente compatible en su tabla y quedaron fuera de la matriz de tasas (`data/model/census_indicator_excluded_raw.csv`), por ejemplo el detalle de "uso de TIC" por sexo y el detalle de migracion por lugar de residencia hace 5 anos.
- Varias tasas quedan casi duplicadas entre si porque distintas tablas del INEC comparten la misma dimension "Sexo al nacer", lo que sobre-representa la razon de sexo de la poblacion frente a otras dimensiones socioeconomicas en el espacio de 667 variables. Antes de usar esta version para inferencia sustantiva conviene deduplicar columnas casi colineales (por ejemplo por correlacion > 0.98) o resumir cada tabla en un numero menor de componentes.
- La reduccion PCA mejora las metricas de separacion pero cambia la interpretabilidad directa de cada eje; el perfil de features reportado usa las variables originales (no los componentes) para mantener la interpretacion.

## Proximos pasos

1. Mapear los clusters para evaluar continuidad territorial y detectar artefactos.
2. Probar robustez con `k=4`, `k=6` y exclusion del cluster urbano de outliers.
3. Estimar modelos supervisados donde el objetivo sea el eje Political Compass y las covariables sean solo censales/satelitales.
4. Incorporar validacion espacial, por ejemplo autocorrelacion Moran o modelos con efectos provinciales.
5. Refinar la clasificacion Political Compass con una matriz documentada de candidatos, ejes y justificacion.
6. Deduplicar tasas censales casi colineales (en particular las repeticiones de "Sexo al nacer") antes de usar el catalogo completo para interpretacion sustantiva.
7. Probar `k=4` con PCA sobre el catalogo censal completo, que obtuvo mejor silhouette que `k=5` en esta extension.

## Archivos reproducibles

- `scripts/build_inec_censo_db.py`: descarga y normaliza tabulados INEC.
- `scripts/validate_inec_population_totals.py`: valida poblacion censal.
- `scripts/build_parish_model_dataset.py`: une fuentes censales, satelitales y electorales.
- `scripts/build_census_indicator_features.py`: extrae los 1,057 indicadores tabulados del INEC a nivel parroquial.
- `scripts/normalize_census_indicators.py`: convierte los indicadores crudos en tasas comparables entre parroquias.
- `scripts/cluster_vote_patterns.py`: ejecuta clustering y perfiles de clusters.
- `scripts/compare_clustering_methods.py`: compara metodos de clustering.
- `data/model/parroquia_features.csv`: matriz parroquial integrada (pipeline curado).
- `data/model/cluster_summary_pc_kmeans_k5.csv`: resumen principal de clusters (pipeline curado).
- `data/model/clustering_method_comparison_pc.csv`: comparacion de metodos (pipeline curado).
- `data/model/census_indicator_features.csv` / `census_indicator_dictionary.csv`: catalogo censal completo, crudo.
- `data/model/census_indicator_features_normalized.csv` / `census_indicator_dictionary_normalized.csv`: catalogo censal completo, normalizado a tasas.
- `data/model/census_indicator_excluded_raw.csv`: indicadores crudos sin denominador confiable, excluidos de las tasas.
- `data/model/parroquia_features_full_census_normalized.csv`: matriz parroquial integrada con el catalogo censal completo normalizado.
- `data/model/cluster_summary_pc_full_census_normalized_kmeans_pca0p9_k5.csv`: resumen principal de clusters de la extension.
- `data/model/clustering_method_comparison_pc_full_census_normalized_pca0p9.csv`: comparacion de metodos de la extension.
