"""Lightweight, dependency-free input checks performed before a job is
accepted, mirroring the limits documented in the main README and enforced
again (authoritatively) by `inference/catrange_inference.py` itself. These
checks exist only to reject obviously bad submissions early, before writing
files or occupying a queue slot; they intentionally do not duplicate the
full per-row sequence/SMILES validation that the pipeline already performs.
"""

from __future__ import annotations

import csv
import io

MIN_SEQUENCE_LENGTH = 9
MAX_SEQUENCE_LENGTH = 1022
MIN_SMILES_LENGTH = 2
MAX_SMILES_LENGTH = 512
MAX_INTERACTIVE_PAIRS = 10
MAX_CSV_BYTES = 15 * 1024 * 1024  # 15 MB, generous for a "bulk-large" CSV
MAX_CSV_ROWS = 5000

REQUIRED_COLUMNS = {"sequence"}
SMILES_COLUMNS = {"Isomeric SMILES", "smiles"}


class ValidationError(ValueError):
    pass


def validate_pairs(pairs: list[dict]) -> None:
    if not pairs:
        raise ValidationError("Provide at least one sequence/SMILES pair.")
    if len(pairs) > MAX_INTERACTIVE_PAIRS:
        raise ValidationError(
            f"Interactive mode accepts at most {MAX_INTERACTIVE_PAIRS} pairs; "
            "use a CSV upload for more."
        )
    for pair in pairs:
        sequence = str(pair.get("sequence", "")).strip()
        smiles = str(pair.get("smiles", "")).strip()
        if not sequence or not smiles:
            raise ValidationError("Each pair needs both a sequence and a SMILES string.")


def validate_csv_bytes(raw: bytes) -> None:
    if len(raw) > MAX_CSV_BYTES:
        raise ValidationError(
            f"CSV file is too large (limit {MAX_CSV_BYTES // (1024 * 1024)} MB)."
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("CSV file must be UTF-8 encoded.") from exc

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValidationError("CSV file has no header row.")
    columns = set(reader.fieldnames)
    if not REQUIRED_COLUMNS.issubset(columns):
        raise ValidationError("CSV file needs a 'sequence' column.")
    if not columns & SMILES_COLUMNS:
        raise ValidationError("CSV file needs an 'Isomeric SMILES' (or 'smiles') column.")

    row_count = sum(1 for _ in reader)
    if row_count == 0:
        raise ValidationError("CSV file has no data rows.")
    if row_count > MAX_CSV_ROWS:
        raise ValidationError(f"CSV file has too many rows (limit {MAX_CSV_ROWS}).")


def pairs_to_csv_text(pairs: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["sequence", "Isomeric SMILES"])
    for pair in pairs:
        writer.writerow([str(pair["sequence"]).strip(), str(pair["smiles"]).strip()])
    return buffer.getvalue()
