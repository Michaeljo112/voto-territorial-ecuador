"""Build a SQLite database from INEC Ecuador 2022 census tabulados.

The public tabulados are Excel-like CSV files: each ZIP contains many numbered
tables, with metadata rows before the real header. This loader keeps the source
shape auditable while also exposing a parish-level view for analysis.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sqlite3
import sys
import unicodedata
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "config" / "inec_censo_2022_tabulados.csv"
DEFAULT_OUT_DIR = ROOT / "data" / "censo_inec"
USER_AGENT = "Mozilla/5.0 (compatible; analisisElectoral/1.0)"


@dataclass(frozen=True)
class Dataset:
    slug: str
    tema: str
    dominio: str
    url: str


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def norm(value: object) -> str:
    return strip_accents(str(value or "")).strip().lower()


def clean_cell(value: object) -> str:
    return str(value or "").replace("\x96", "-").strip()


def safe_name(url: str) -> str:
    return urllib.request.urlparse(url).path.rsplit("/", 1)[-1]


def read_manifest(path: Path) -> list[Dataset]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [Dataset(**row) for row in csv.DictReader(handle)]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path, force: bool = False) -> None:
    if target.exists() and not force:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        target.write_bytes(response.read())


def decode_csv(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def iter_csv_files(zip_path: Path) -> Iterable[tuple[str, list[list[str]]]]:
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            if not member.lower().endswith(".csv"):
                continue
            text = decode_csv(archive.read(member))
            reader = csv.reader(io.StringIO(text))
            yield member, [[clean_cell(cell) for cell in row] for row in reader]


def metadata_from_rows(rows: list[list[str]]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    keys = {
        "tabla n": "table_number",
        "tabla no": "table_number",
        "nombre de la tabla": "table_name",
        "fuente": "source",
        "elaboracion": "elaboration",
    }
    for row in rows[:10]:
        for idx, cell in enumerate(row):
            key = norm(cell).replace(":", "").replace("°", "").strip()
            if key in keys and idx + 1 < len(row):
                metadata[keys[key]] = clean_cell(row[idx + 1])
    return metadata


def is_blank_row(row: list[str]) -> bool:
    return not any(clean_cell(cell) for cell in row)


def find_header_start(rows: list[list[str]]) -> int | None:
    for idx, row in enumerate(rows):
        cells = [norm(cell) for cell in row]
        joined = " ".join(cells)
        if "indice" in cells or joined.startswith("indice "):
            return idx
    return None


def first_data_row(rows: list[list[str]], header_start: int) -> int:
    idx = header_start + 1
    while idx < len(rows):
        row = rows[idx]
        if is_blank_row(row):
            idx += 1
            break
        idx += 1
    while idx < len(rows) and is_blank_row(rows[idx]):
        idx += 1
    return idx


def merge_headers(rows: list[list[str]], start: int, end: int, width: int) -> list[str]:
    filled_rows: list[list[str]] = []
    for row in rows[start:end]:
        filled: list[str] = []
        last = ""
        for col_idx in range(width):
            part = clean_cell(row[col_idx] if col_idx < len(row) else "")
            if part:
                last = part
            filled.append(last)
        filled_rows.append(filled)

    labels: list[str] = []
    for col_idx in range(width):
        parts: list[str] = []
        for row in filled_rows:
            part = clean_cell(row[col_idx])
            if part and part not in parts:
                parts.append(part)
        labels.append(" | ".join(parts) or f"col_{col_idx + 1}")
    return labels


NUMBER_RE = re.compile(r"^-?[\d,.]+%?$")


def parse_number(value: str) -> float | None:
    value = clean_cell(value)
    if not value or not NUMBER_RE.match(value):
        return None
    value = value.replace("%", "").replace(",", "")
    try:
        return float(value)
    except ValueError:
        return None


def likely_numeric_column(rows: list[list[str]], col_idx: int, sample_start: int) -> bool:
    seen = 0
    numeric = 0
    for row in rows[sample_start : sample_start + 80]:
        if col_idx >= len(row):
            continue
        cell = clean_cell(row[col_idx])
        if not cell:
            continue
        seen += 1
        if parse_number(cell) is not None:
            numeric += 1
    return seen > 0 and numeric / seen >= 0.8


def infer_columns(rows: list[list[str]], header_start: int) -> tuple[list[str], int, int]:
    data_start = first_data_row(rows, header_start)
    width = max((len(row) for row in rows), default=0)
    header_end = max(header_start + 1, data_start - 1)
    labels = merge_headers(rows, header_start, header_end, width)
    numeric_start = next(
        (idx for idx in range(width) if likely_numeric_column(rows, idx, data_start)),
        width,
    )
    return labels, data_start, numeric_start


def normalize_geo(dimensions: list[str]) -> tuple[str | None, str | None, str | None, str]:
    province = dimensions[0] if len(dimensions) > 0 else None
    canton = dimensions[1] if len(dimensions) > 1 else None
    parish = dimensions[2] if len(dimensions) > 2 else None
    level = "otro"
    if parish and norm(parish) not in {"nacional"} and not norm(parish).startswith("total "):
        level = "parroquia"
    elif canton and norm(canton) not in {"nacional"} and not norm(canton).startswith("total "):
        level = "canton"
    elif province and norm(province) not in {"nacional", "total nacional"}:
        level = "provincia"
    elif any(norm(item) in {"nacional", "total nacional"} for item in dimensions[:3]):
        level = "nacional"
    return province, canton, parish, level


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        pragma journal_mode = wal;
        pragma synchronous = normal;
        pragma temp_store = memory;
        """
    )
    conn.executescript(
        """
        drop table if exists datasets;
        drop table if exists source_files;
        drop table if exists tabulados;
        drop table if exists observations;
        drop view if exists v_observations_parroquia;

        create table datasets (
            slug text primary key,
            tema text not null,
            dominio text not null,
            url text not null
        );

        create table source_files (
            slug text primary key references datasets(slug),
            zip_path text not null,
            sha256 text not null,
            bytes integer not null
        );

        create table tabulados (
            id integer primary key,
            slug text not null references datasets(slug),
            csv_name text not null,
            table_number text,
            table_name text,
            source text,
            elaboration text,
            original_headers_json text not null,
            data_rows integer not null
        );

        create table observations (
            id integer primary key,
            tabulado_id integer not null references tabulados(id),
            slug text not null,
            csv_name text not null,
            row_number integer not null,
            geography_level text not null,
            provincia text,
            canton text,
            parroquia text,
            dimension_1 text,
            dimension_2 text,
            dimension_3 text,
            dimension_4 text,
            dimension_5 text,
            dimensions_json text not null,
            metric text not null,
            value real,
            raw_value text not null
        );
        """
    )


def finalize_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create index idx_obs_slug on observations(slug);
        create index idx_obs_tabulado on observations(tabulado_id);
        create index idx_obs_validation_geo on observations(
            tabulado_id, geography_level, metric, provincia, canton, parroquia
        );
        create index idx_obs_geo on observations(geography_level, provincia, canton, parroquia);
        create index idx_tab_slug on tabulados(slug);

        create view v_observations_parroquia as
        select
            d.dominio,
            d.tema,
            t.table_number,
            t.table_name,
            o.slug,
            o.csv_name,
            o.provincia,
            o.canton,
            o.parroquia,
            o.dimension_4,
            o.dimension_5,
            o.dimensions_json,
            o.metric,
            o.value,
            o.raw_value
        from observations o
        join tabulados t on t.id = o.tabulado_id
        join datasets d on d.slug = o.slug
        where o.geography_level = 'parroquia';
        """
    )


def load_dataset(conn: sqlite3.Connection, dataset: Dataset, zip_path: Path) -> tuple[int, int]:
    conn.execute(
        "insert into datasets(slug, tema, dominio, url) values (?, ?, ?, ?)",
        (dataset.slug, dataset.tema, dataset.dominio, dataset.url),
    )
    conn.execute(
        "insert into source_files(slug, zip_path, sha256, bytes) values (?, ?, ?, ?)",
        (dataset.slug, str(zip_path), sha256(zip_path), zip_path.stat().st_size),
    )
    table_count = 0
    observation_count = 0
    for csv_name, rows in iter_csv_files(zip_path):
        if norm(Path(csv_name).name).startswith("indice"):
            continue
        header_start = find_header_start(rows)
        if header_start is None:
            continue
        metadata = metadata_from_rows(rows)
        labels, data_start, numeric_start = infer_columns(rows, header_start)
        tab_cursor = conn.execute(
            """
            insert into tabulados(
                slug, csv_name, table_number, table_name, source, elaboration,
                original_headers_json, data_rows
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset.slug,
                csv_name,
                metadata.get("table_number"),
                metadata.get("table_name"),
                metadata.get("source"),
                metadata.get("elaboration"),
                json.dumps(labels, ensure_ascii=False),
                max(0, len(rows) - data_start),
            ),
        )
        tabulado_id = int(tab_cursor.lastrowid)
        table_count += 1
        for row_idx, row in enumerate(rows[data_start:], start=data_start + 1):
            if is_blank_row(row):
                continue
            padded = row + [""] * max(0, len(labels) - len(row))
            raw_dims = [clean_cell(cell) for cell in padded[:numeric_start]]
            if raw_dims and norm(raw_dims[0]) in {"indice", ""}:
                raw_dims = raw_dims[1:]
            dimensions = [cell for cell in raw_dims if cell]
            if not dimensions:
                continue
            province, canton, parish, level = normalize_geo(dimensions)
            dim_slots = (dimensions + [None] * 5)[:5]
            for col_idx in range(numeric_start, len(labels)):
                raw_value = clean_cell(padded[col_idx] if col_idx < len(padded) else "")
                if raw_value == "":
                    continue
                conn.execute(
                    """
                    insert into observations(
                        tabulado_id, slug, csv_name, row_number, geography_level,
                        provincia, canton, parroquia,
                        dimension_1, dimension_2, dimension_3, dimension_4, dimension_5,
                        dimensions_json, metric, value, raw_value
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tabulado_id,
                        dataset.slug,
                        csv_name,
                        row_idx,
                        level,
                        province,
                        canton,
                        parish,
            *dim_slots,
                        json.dumps(dimensions, ensure_ascii=False),
                        labels[col_idx],
                        parse_number(raw_value),
                        raw_value,
                    ),
                )
                observation_count += 1
    return table_count, observation_count


def build_database(manifest: Path, out_dir: Path, db_path: Path, force_download: bool) -> None:
    datasets = read_manifest(manifest)
    raw_dir = out_dir / "raw"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        init_db(conn)
        for dataset in datasets:
            zip_path = raw_dir / safe_name(dataset.url)
            print(f"Descargando/verificando {dataset.slug}: {zip_path.name}", flush=True)
            download(dataset.url, zip_path, force=force_download)
            tables, observations = load_dataset(conn, dataset, zip_path)
            print(f"  {tables} tabulados, {observations:,} observaciones", flush=True)
        print("Creando indices y vista parroquial", flush=True)
        finalize_db(conn)
        conn.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--db", type=Path, default=DEFAULT_OUT_DIR / "censo_inec_2022_tabulados.sqlite")
    parser.add_argument("--force-download", action="store_true")
    args = parser.parse_args(argv)
    build_database(args.manifest, args.out_dir, args.db, args.force_download)
    print(f"Base lista: {args.db}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
