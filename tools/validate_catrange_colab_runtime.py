#!/usr/bin/env python3
"""Static validation for the patched CatRange Colab notebook."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import tempfile
from pathlib import Path


RELEASE = "2026-08-28-python-runtime-stability-test"
FORBIDDEN = (
    "--bootstrap-python",
    "get-pip.py",
    "python3.12 -m pip",
    "python3.10 -m pip",
    "python3.12-venv",
    "python3.10-venv",
    "ensurepip",
    "\n+    '",
)
REQUIRED = (
    '"--clean-python"',
    '"3.12"',
    'UV_VERSION = "0.8.14"',
    'MECH_ENV="${CATRANGE_RUNTIME_DIR}/mechanistic-py312"',
    'BINARY_ENV="${CATRANGE_RUNTIME_DIR}/binary-py310"',
    'transformers==4.46.3',
    'CLEAN_STANDALONE_BOOTSTRAPPED=1 "${CLEAN_PYTHON}"',
)


def extract_embedded_runner(pipeline: str) -> str:
    prefix = "standalone_clean_script.write_text("
    start = pipeline.index(prefix) + len(prefix)
    end = pipeline.index(")\nstandalone_clean_script.chmod(0o755)", start)
    return ast.literal_eval(pipeline[start:end])


def extract_python_heredocs(pipeline: str) -> list[str]:
    lines = pipeline.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        if "<<'PY'" not in lines[index]:
            index += 1
            continue
        start = index + 1
        end = start
        while end < len(lines) and lines[end] != "PY":
            end += 1
        if end >= len(lines):
            raise RuntimeError(f"Unterminated Python heredoc beginning at pipeline line {index + 1}.")
        blocks.append("\n".join(lines[start:end]) + "\n")
        index = end + 1
    return blocks


def validate(notebook_path: Path, bash_path: Path | None) -> list[str]:
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    if notebook.get("nbformat") != 4:
        raise RuntimeError("Expected notebook format 4.")

    cells = notebook.get("cells", [])
    pipeline_cells = [
        "".join(cell.get("source", []))
        for cell in cells
        if "#@title 2. Run CLEAN + CatRange Inference pipeline" in "".join(cell.get("source", []))
    ]
    if len(pipeline_cells) != 1:
        raise RuntimeError(f"Expected one pipeline cell; found {len(pipeline_cells)}.")
    pipeline = pipeline_cells[0]

    for fragment in FORBIDDEN:
        if fragment in pipeline:
            raise RuntimeError(f"Forbidden legacy fragment remains: {fragment}")
    for fragment in REQUIRED:
        if fragment not in pipeline:
            raise RuntimeError(f"Required runtime fragment is missing: {fragment}")

    notebook_text = notebook_path.read_text(encoding="utf-8")
    if RELEASE not in notebook_text:
        raise RuntimeError("Notebook release marker was not updated.")
    for index, cell in enumerate(cells):
        if cell.get("cell_type") == "code":
            if cell.get("execution_count") is not None:
                raise RuntimeError(f"Code cell {index} retained an execution count.")
            if cell.get("outputs"):
                raise RuntimeError(f"Code cell {index} retained outputs.")

    embedded_runner = extract_embedded_runner(pipeline)
    compile(embedded_runner, "standalone_clean_inference.py", "exec")

    heredocs = extract_python_heredocs(pipeline)
    if len(heredocs) < 5:
        raise RuntimeError(f"Expected at least five Python heredocs; found {len(heredocs)}.")
    for index, block in enumerate(heredocs, start=1):
        compile(block, f"pipeline-heredoc-{index}.py", "exec")

    binary_marker = pipeline.index("# ---------------------------- BINARY BRANCH")
    merge_marker = pipeline.index("[CLEAN] Merging EC annotations back into inference_results.csv")
    final_summary_marker = pipeline.index('results_path = Path("inference_results.csv")', merge_marker)
    if not (binary_marker < merge_marker < final_summary_marker):
        raise RuntimeError("CLEAN merge is not positioned after both inference branches.")

    checks = [
        "notebook JSON parsed",
        "all notebook outputs and execution counts cleared",
        "embedded CLEAN runner compiled",
        f"{len(heredocs)} Python heredocs compiled",
        "legacy Colab Python bootstrap fragments absent",
        "managed Python 3.12/3.10 environments present",
        "CLEAN merge positioned after both inference branches",
    ]

    if bash_path is not None:
        with tempfile.TemporaryDirectory(prefix="catrange-colab-") as temp_dir:
            pipeline_path = Path(temp_dir) / "pipeline.sh"
            pipeline_path.write_text(pipeline, encoding="utf-8", newline="\n")
            result = subprocess.run(
                [str(bash_path), "-n", str(pipeline_path)],
                text=True,
                capture_output=True,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    "bash -n failed:\n" + (result.stdout or "") + (result.stderr or "")
                )
        checks.append("complete pipeline passed bash -n")
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notebook", type=Path)
    parser.add_argument("--bash", type=Path, default=None)
    args = parser.parse_args()
    checks = validate(args.notebook.resolve(), args.bash.resolve() if args.bash else None)
    print("Validation passed:")
    for check in checks:
        print(f"- {check}")


if __name__ == "__main__":
    main()
