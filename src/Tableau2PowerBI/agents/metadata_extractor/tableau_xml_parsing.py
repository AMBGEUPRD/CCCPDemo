"""Helper functions for parsing Tableau workbook XML and TWBX archives."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile

logger = logging.getLogger(__name__)

_LAST_BRACKET_PATTERN = re.compile(r"\[([^\[\]]+)\]$")
SIMPLE_FIELD_PATTERN = re.compile(r"^\[([^\[\]]+)\]$")
SHELF_SPLIT_PATTERN = re.compile(r"\s*[*/]\s*")
_EXPRESSION_AGG_CODES = frozenset({"fval", "pcto", "pctd"})
TABLEAU_VIRTUAL_FIELDS = frozenset({"Measure Names", "Measure Values"})


def parse_field_ref(ref: str) -> dict[str, str | None]:
    """Parse a Tableau field reference into aggregation, field, and type code."""
    if not ref:
        return {"raw": ref}

    simple = SIMPLE_FIELD_PATTERN.match(ref)
    if simple:
        return {"field": simple.group(1), "raw": ref}

    last_bracket = _LAST_BRACKET_PATTERN.search(ref)
    if not last_bracket:
        return {"raw": ref}

    content = last_bracket.group(1)
    if content.startswith(":"):
        return {"aggregation": None, "field": content[1:] or None, "type_code": None, "raw": ref}

    parts = content.split(":")
    if len(parts) == 1:
        return {"aggregation": None, "field": parts[0] or None, "type_code": None, "raw": ref}
    if len(parts) == 2:
        return {"aggregation": parts[0], "field": parts[1] or None, "type_code": None, "raw": ref}
    if len(parts) == 3:
        return {"aggregation": parts[0], "field": parts[1] or None, "type_code": parts[2], "raw": ref}

    outer_agg = parts[0]
    if outer_agg.lower() in _EXPRESSION_AGG_CODES:
        return {
            "aggregation": outer_agg,
            "field": parts[2] or None,
            "type_code": parts[3] if len(parts) > 3 else None,
            "raw": ref,
        }

    return {
        "aggregation": parts[0],
        "field": ":".join(parts[1:-1]) or None,
        "type_code": parts[-1],
        "raw": ref,
    }


def parse_shelf(shelf_text: str) -> list[dict[str, str | None]]:
    """Parse a Tableau shelf expression into a list of field references."""
    if not shelf_text:
        return []

    parts = SHELF_SPLIT_PATTERN.split(shelf_text.strip())
    cleaned = [part.strip().strip("()") for part in parts]
    return [parse_field_ref(part) for part in cleaned if part]


def parse_xml_root(path: Path) -> ET.Element:
    """Parse a Tableau XML file from disk and return its root element."""
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"Invalid Tableau workbook XML: {path}") from exc


def parse_xml_bytes(xml_bytes: bytes, source_path: Path) -> ET.Element:
    """Parse Tableau XML bytes from an archive and return the root element."""
    try:
        return ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid Tableau workbook XML inside package: {source_path}") from exc


def load_tableau_workbook_root(path: Path) -> ET.Element:
    """Load the XML root from a .twb file or from inside a .twbx archive."""
    ext = path.suffix.lower()
    if ext == ".twb":
        return parse_xml_root(path)

    if ext == ".twbx":
        try:
            with ZipFile(path, "r") as workbook_zip:
                twb_entries = sorted(
                    (
                        name
                        for name in workbook_zip.namelist()
                        if name.lower().endswith(".twb") and not name.endswith("/")
                    ),
                    key=lambda name: (len(Path(name).parts), name.lower()),
                )
                if not twb_entries:
                    raise ValueError(f"No .twb workbook found inside TWBX package: {path}")

                with workbook_zip.open(twb_entries[0], "r") as twb_file:
                    return parse_xml_bytes(twb_file.read(), path)
        except BadZipFile as exc:
            raise ValueError(f"Invalid TWBX package: {path}") from exc

    raise ValueError(f"Unsupported Tableau file extension '{path.suffix}'. Expected .twb or .twbx")


def extract_data_files_from_twbx(twbx_path: Path, output_dir: Path) -> dict[str, Path]:
    """Extract non-TWB data files from a TWBX archive to output_dir."""
    if twbx_path.suffix.lower() != ".twbx":
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    file_mapping: dict[str, Path] = {}

    try:
        with ZipFile(twbx_path, "r") as archive:
            for entry in archive.namelist():
                if entry.endswith("/") or entry.lower().endswith(".twb"):
                    continue

                target = resolve_archive_target(output_dir, entry)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry, "r") as src:
                    target.write_bytes(src.read())

                file_mapping[entry] = target.resolve()
                logger.info("Extracted: %s", target.name)
    except BadZipFile as exc:
        raise ValueError(f"Invalid TWBX package: {twbx_path}") from exc

    return file_mapping


def resolve_archive_target(output_dir: Path, entry: str) -> Path:
    """Resolve a TWBX archive entry under output_dir, rejecting path escapes."""
    normalised_entry = entry.replace("\\", "/")
    archive_path = PurePosixPath(normalised_entry)

    if archive_path.is_absolute() or any(part == ".." for part in archive_path.parts):
        raise ValueError(f"Unsafe TWBX archive entry: {entry}")

    safe_parts = [part for part in archive_path.parts if part and part != "."]
    if not safe_parts:
        raise ValueError(f"Unsafe TWBX archive entry: {entry}")

    target = (output_dir / Path(*safe_parts)).resolve()
    output_root = output_dir.resolve()
    if target != output_root and output_root not in target.parents:
        raise ValueError(f"Unsafe TWBX archive entry: {entry}")

    return target


def resolve_connection_paths(
    metadata: dict[str, Any],
    file_mapping: dict[str, Path],
) -> dict[str, Any]:
    """Enrich each datasource connection with resolved embedded-file paths."""
    if not file_mapping:
        return metadata

    normalised_map: dict[str, tuple[str, Path]] = {}
    basename_map: dict[str, list[tuple[str, Path]]] = {}
    for archive_path, abs_path in file_mapping.items():
        normalised_map[archive_path.replace("\\", "/").lower()] = (archive_path, abs_path)
        basename = Path(archive_path).name.lower()
        basename_map.setdefault(basename, []).append((archive_path, abs_path))

    for datasource in metadata.get("datasources", []):
        connection = datasource.get("connection")
        if not connection or not isinstance(connection, dict):
            continue

        filename = connection.get("filename")
        if not filename:
            continue

        archive_key: str | None = None
        resolved: Path | None = None

        if filename in file_mapping:
            archive_key = filename
            resolved = file_mapping[filename]

        if resolved is None:
            key = filename.replace("\\", "/").lower()
            entry = normalised_map.get(key)
            if entry:
                archive_key, resolved = entry

        if resolved is None:
            basename = Path(filename).name.lower()
            matches = basename_map.get(basename, [])
            if len(matches) > 1:
                raise ValueError(
                    f"Ambiguous embedded file match for '{filename}'. Candidates: "
                    + ", ".join(path for path, _ in matches)
                )
            if matches:
                archive_key, resolved = matches[0]

        if resolved is not None and archive_key is not None:
            connection["resolved_filename"] = str(resolved)
            connection["relative_path"] = archive_key
            logger.info("Resolved connection: %s", Path(filename).name)

    return metadata
