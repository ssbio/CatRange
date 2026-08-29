#!/usr/bin/env python3
"""Standalone CLEAN runner with isolated environment bootstrapping.

Screen mode:
  - accepts CSV or FASTA input
  - downloads CLEAN + pretrained weights automatically
  - runs CLEAN inference in a dedicated venv to avoid esm conflicts
  - labels each sequence as enzyme/non-enzyme using CLEAN GMM confidence
  - can write a catrange-ready filtered CSV containing only enzyme rows

Merge mode:
  - merges a catrange output CSV back into the screened CLEAN CSV by clean_row_id
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


BOOTSTRAP_ENV_VAR = "CLEAN_STANDALONE_BOOTSTRAPPED"
# CATRANGE_FRIENDLY_CLEAN_OUTPUT_V1
UV_VERSION = "0.8.14"
DEFAULT_CLEAN_PYTHON = "3.12"
CLEAN_REQUIREMENTS = ('torch==2.4.1', 'numpy==1.26.4', 'pandas==2.2.3', 'scikit-learn==1.5.2', 'scipy==1.11.4', 'tqdm==4.66.5', 'fair-esm==2.0.0', 'pysam==0.22.1', 'easydict==1.13', 'gdown==5.2.0')
CLEAN_IMPORTS = (
    "torch", "numpy", "pandas", "sklearn", "scipy",
    "tqdm", "esm", "pysam", "easydict", "gdown",
)
DEFAULT_PRETRAINED_URL = (
    "https://drive.google.com/file/d/1kwYd4VtzYuMvJMWXy6Vks91DSUAOcKpZ/view?usp=sharing"
)
DEFAULT_REPO_URL = "https://github.com/tttianhao/CLEAN.git"
DEFAULT_REPO_REF = "f2bf2a4f497fa2cc87dac2a1bb314fee587c0a15"
REQUIRED_PRETRAINED_FILES = {
    "100.pt",
    "70.pt",
    "split100.pth",
    "split70.pth",
    "gmm_ensumble.pkl",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir",
        default=str(Path.cwd() / ".clean_runtime"),
        help="Directory for the isolated env, repo clone, downloads, and temp files.",
    )
    parser.add_argument(
        "--clean-repo-dir",
        default=None,
        help="Optional existing CLEAN checkout to reuse instead of cloning a new one.",
    )
    parser.add_argument(
        "--repo-url",
        default=DEFAULT_REPO_URL,
        help="CLEAN git repository URL used when cloning is required.",
    )
    parser.add_argument(
        "--repo-ref",
        default=DEFAULT_REPO_REF,
        help="Pinned CLEAN commit or ref used by the managed checkout.",
    )
    parser.add_argument(
        "--pretrained-url",
        default=DEFAULT_PRETRAINED_URL,
        help="Google Drive URL for the pretrained CLEAN assets zip.",
    )
    parser.add_argument(
        "--clean-python",
        default=DEFAULT_CLEAN_PYTHON,
        help="Managed Python major.minor used for CLEAN (default: 3.12).",
    )
    parser.add_argument(
        "--train-data",
        default="split100",
        choices=["split70", "split100"],
        help="Which pretrained split to use for CLEAN inference.",
    )
    parser.add_argument(
        "--non-enzyme-threshold",
        type=float,
        default=0.5,
        help=(
            "Minimum CLEAN top-hit GMM confidence required to call a sequence an enzyme. "
            "CLEAN does not publish an official non-enzyme cutoff; 0.5 is the default decision boundary."
        ),
    )
    parser.add_argument(
        "--toks-per-batch",
        type=int,
        default=2048,
        help="Token budget per ESM batch passed through CLEAN_inference.py.",
    )
    parser.add_argument(
        "--esm-batches-per-clean-inference",
        type=int,
        default=200,
        help="How many ESM batches to accumulate before EC inference inside CLEAN.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print extra progress details.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    screen = subparsers.add_parser("screen", help="Run standalone CLEAN screening + EC prediction.")
    screen.add_argument("--input-csv", default=None, help="Input CSV containing a sequence column.")
    screen.add_argument("--input-fasta", default=None, help="Input FASTA file.")
    screen.add_argument(
        "--sequence-column",
        default="sequence",
        help="Sequence column name when using --input-csv.",
    )
    screen.add_argument(
        "--output-csv",
        required=True,
        help="Path to the augmented CSV with CLEAN outputs.",
    )
    screen.add_argument(
        "--job-name",
        default=None,
        help="Optional job slug used for intermediate CLEAN filenames.",
    )
    screen.add_argument(
        "--write-catrange-ready-csv",
        default=None,
        help="Optional path for a filtered CSV containing only rows marked as enzymes.",
    )

    merge = subparsers.add_parser("merge", help="Merge catrange results back into screened CLEAN output.")
    merge.add_argument("--screened-csv", required=True, help="CSV previously created by the screen command.")
    merge.add_argument(
        "--catrange-output-csv",
        required=True,
        help="CSV emitted by the catrange stage using the filtered catrange-ready CSV.",
    )
    merge.add_argument("--output-csv", required=True, help="Path for the final merged CSV.")

    return parser.parse_args()


def log(message: str) -> None:
    print(message, flush=True)


def run(
    command: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    capture_output: bool = False,
    quiet: bool = True,
) -> subprocess.CompletedProcess[str]:
    if capture_output:
        return subprocess.run(
            list(command),
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
    if not quiet:
        return subprocess.run(
            list(command),
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            check=True,
        )

    result = subprocess.run(
        list(command),
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
        if combined_output:
            tail = "\n".join(combined_output.splitlines()[-40:])
            log("[error] Last lines from the failed command:")
            print(tail, flush=True)
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def uv_environment(work_dir: Path) -> Dict[str, str]:
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = str(work_dir / "uv-cache")
    env["UV_PYTHON_INSTALL_DIR"] = str(work_dir / "uv-python")
    env["UV_MANAGED_PYTHON"] = "1"
    env["UV_LINK_MODE"] = "copy"
    return env


def ensure_uv(work_dir: Path) -> Path:
    # CATRANGE_CLEAN_LINUX_MESSAGE_V1
    if platform.system().lower() != "linux":
        raise RuntimeError(
            "Automatic CLEAN setup currently requires Linux. "
            "On Windows, run CatRange inside WSL."
        )

    uv_bin = work_dir / "uv-bin" / "uv"
    if uv_bin.exists():
        result = subprocess.run(
            [str(uv_bin), "--version"],
            text=True,
            capture_output=True,
        )
        if result.returncode == 0 and result.stdout.strip() == f"uv {UV_VERSION}":
            return uv_bin
        uv_bin.unlink()

    uv_bin.parent.mkdir(parents=True, exist_ok=True)
    machine = platform.machine().lower()
    targets = {
        "x86_64": "x86_64-unknown-linux-gnu",
        "amd64": "x86_64-unknown-linux-gnu",
        "aarch64": "aarch64-unknown-linux-gnu",
        "arm64": "aarch64-unknown-linux-gnu",
    }
    target = targets.get(machine)
    if target is None:
        raise RuntimeError(f"Unsupported Linux architecture for uv: {machine}")

    archive_path = work_dir / f"uv-{UV_VERSION}-{target}.tar.gz"
    download_path = archive_path.with_suffix(archive_path.suffix + ".download")
    staged_uv = uv_bin.with_suffix(".download")
    release_url = (
        f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/"
        f"uv-{target}.tar.gz"
    )
    try:
        run(
            [
                "curl",
                "-fL",
                "--retry",
                "3",
                "--retry-all-errors",
                release_url,
                "-o",
                str(download_path),
            ],
        )
        download_path.replace(archive_path)
        with tarfile.open(archive_path, "r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.isfile() and Path(member.name).name == "uv"
            ]
            if len(members) != 1:
                raise RuntimeError(
                    f"Expected one uv binary in {archive_path}; found {len(members)}."
                )
            source = archive.extractfile(members[0])
            if source is None:
                raise RuntimeError(f"Could not read uv binary from {archive_path}.")
            with source, staged_uv.open("wb") as destination:
                shutil.copyfileobj(source, destination)
        staged_uv.chmod(0o755)
        staged_uv.replace(uv_bin)
    finally:
        archive_path.unlink(missing_ok=True)
        download_path.unlink(missing_ok=True)
        staged_uv.unlink(missing_ok=True)

    result = run([str(uv_bin), "--version"], capture_output=True)
    if result.stdout.strip() != f"uv {UV_VERSION}":
        uv_bin.unlink(missing_ok=True)
        raise RuntimeError(
            f"Expected uv {UV_VERSION}, received {result.stdout.strip()!r}."
        )
    return uv_bin


def environment_fingerprint(python_spec: str) -> str:
    payload = "\n".join((UV_VERSION, python_spec, *CLEAN_REQUIREMENTS)).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_clean_env(python_bin: Path, python_spec: str) -> bool:
    if not python_bin.exists():
        return False
    try:
        expected_python = tuple(int(part) for part in python_spec.split(".")[:2])
        if len(expected_python) != 2:
            return False
    except ValueError:
        return False

    expected_versions = dict(item.split("==", 1) for item in CLEAN_REQUIREMENTS)
    validation_code = (
        "import importlib,sys\n"
        "from importlib.metadata import version\n"
        f"assert sys.version_info[:2] == {expected_python!r}, sys.version\n"
        f"expected = {expected_versions!r}\n"
        "for distribution, expected_version in expected.items():\n"
        "    actual = version(distribution)\n"
        "    assert actual == expected_version, (distribution, actual, expected_version)\n"
        f"for module in {CLEAN_IMPORTS!r}:\n"
        "    importlib.import_module(module)\n"
    )
    result = subprocess.run(
        [str(python_bin), "-c", validation_code],
        text=True,
        capture_output=True,
        timeout=180,
    )
    return result.returncode == 0


def acquire_environment_lock(lock_dir: Path, timeout_seconds: int = 900) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            lock_dir.mkdir()
            return
        except FileExistsError:
            try:
                age_seconds = time.time() - lock_dir.stat().st_mtime
            except FileNotFoundError:
                continue
            if age_seconds > timeout_seconds:
                shutil.rmtree(lock_dir, ignore_errors=True)
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for CLEAN environment lock: {lock_dir}")
            time.sleep(2)


def resolve_work_dir(raw_work_dir: str) -> Path:
    work_dir = Path(raw_work_dir).expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def resolve_repo_dir(args: argparse.Namespace, work_dir: Path) -> Path:
    if args.clean_repo_dir:
        return Path(args.clean_repo_dir).expanduser().resolve()
    return (work_dir / "CLEAN_repo").resolve()


def ensure_clean_env(args: argparse.Namespace, work_dir: Path) -> Path:
    env_dir = work_dir / "clean_env"
    python_bin = env_dir / "bin" / "python"
    marker_path = env_dir / ".bootstrap_complete"
    lock_dir = work_dir / ".clean_env.lock"
    fingerprint = environment_fingerprint(args.clean_python)
    requirements_path = work_dir / "clean-requirements.txt"
    requirements_text = "\n".join(CLEAN_REQUIREMENTS) + "\n"
    if not requirements_path.exists() or requirements_path.read_text() != requirements_text:
        requirements_path.write_text(requirements_text)

    if (
        marker_path.exists()
        and marker_path.read_text().strip() == fingerprint
        and validate_clean_env(python_bin, args.clean_python)
    ):
        log("[1/3] Runtime ready (cached).")
        return python_bin

    acquire_environment_lock(lock_dir)
    try:
        if (
            marker_path.exists()
            and marker_path.read_text().strip() == fingerprint
            and validate_clean_env(python_bin, args.clean_python)
        ):
            log("[1/3] Runtime ready (cached).")
            return python_bin

        if env_dir.exists():
            log("[1/3] Refreshing an incomplete runtime...")
            shutil.rmtree(env_dir)

        uv_bin = ensure_uv(work_dir)
        uv_env = uv_environment(work_dir)
        log("[1/3] Installing runtime dependencies (first run only)...")
        try:
            run([str(uv_bin), "python", "install", args.clean_python], env=uv_env)
            run(
                [
                    str(uv_bin),
                    "venv",
                    "--managed-python",
                    "--python",
                    args.clean_python,
                    str(env_dir),
                ],
                env=uv_env,
            )
            run(
                [
                    str(uv_bin),
                    "pip",
                    "install",
                    "--python",
                    str(python_bin),
                    "-r",
                    str(requirements_path),
                ],
                env=uv_env,
            )
            if not validate_clean_env(python_bin, args.clean_python):
                raise RuntimeError("CLEAN environment validation failed after installation.")
            marker_path.write_text(fingerprint + "\n")
        except Exception:
            shutil.rmtree(env_dir, ignore_errors=True)
            raise
        return python_bin
    finally:
        shutil.rmtree(lock_dir, ignore_errors=True)


def ensure_clean_repo(args: argparse.Namespace, repo_dir: Path) -> None:
    app_dir = repo_dir / "app"
    entrypoint = app_dir / "CLEAN_inference.py"
    if args.clean_repo_dir:
        if not entrypoint.exists():
            raise FileNotFoundError(
                f"The provided CLEAN checkout is missing {entrypoint}."
            )
        return

    if entrypoint.exists():
        current_ref = run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True,
        ).stdout.strip()
        if current_ref == args.repo_ref:
            return
        log("      Refreshing the managed CLEAN source files...")
        run(
            ["git", "-C", str(repo_dir), "fetch", "--depth", "1", "origin", args.repo_ref]
        )
        run(["git", "-C", str(repo_dir), "checkout", "--detach", "FETCH_HEAD"])
        if not entrypoint.exists():
            raise RuntimeError("The pinned CLEAN checkout is missing app/CLEAN_inference.py.")
        return

    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    log("      Downloading required CLEAN files...")
    run(["git", "clone", "--depth", "1", args.repo_url, str(repo_dir)])
    run(
        ["git", "-C", str(repo_dir), "fetch", "--depth", "1", "origin", args.repo_ref]
    )
    run(["git", "-C", str(repo_dir), "checkout", "--detach", "FETCH_HEAD"])
    if not entrypoint.exists():
        raise RuntimeError("The pinned CLEAN checkout is missing app/CLEAN_inference.py.")


def ensure_pretrained_assets(
    python_bin: Path,
    repo_dir: Path,
    pretrained_url: str,
    work_dir: Path,
) -> None:
    pretrained_dir = repo_dir / "app" / "data" / "pretrained"
    pretrained_dir.mkdir(parents=True, exist_ok=True)
    missing = [name for name in REQUIRED_PRETRAINED_FILES if not (pretrained_dir / name).exists()]
    if not missing:
        return

    log("      Downloading the CLEAN model...")
    zip_path = work_dir / "clean_pretrained.zip"
    run([str(python_bin), "-m", "gdown", "--fuzzy", pretrained_url, "-O", str(zip_path)])

    extract_dir = work_dir / "clean_pretrained_extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(extract_dir)

    copied = set()
    for path in extract_dir.rglob("*"):
        if path.is_file() and path.name in REQUIRED_PRETRAINED_FILES:
            shutil.copy2(path, pretrained_dir / path.name)
            copied.add(path.name)

    missing = [name for name in REQUIRED_PRETRAINED_FILES if not (pretrained_dir / name).exists()]
    if missing:
        raise RuntimeError(
            "Downloaded CLEAN assets but could not find all required files: " + ", ".join(sorted(missing))
        )


def maybe_bootstrap_and_reexec(args: argparse.Namespace) -> None:
    if os.environ.get(BOOTSTRAP_ENV_VAR) == "1":
        return

    work_dir = resolve_work_dir(args.work_dir)
    python_bin = ensure_clean_env(args, work_dir)
    repo_dir = resolve_repo_dir(args, work_dir)
    ensure_clean_repo(args, repo_dir)
    ensure_pretrained_assets(python_bin, repo_dir, args.pretrained_url, work_dir)

    env = os.environ.copy()
    env[BOOTSTRAP_ENV_VAR] = "1"
    run([str(python_bin), str(Path(__file__).resolve()), *sys.argv[1:]], env=env, quiet=False)
    raise SystemExit(0)


def bootstrap_mode_python() -> Path:
    return Path(sys.executable)


def normalize_sequence(sequence: object) -> str:
    if sequence is None:
        return ""
    sequence = str(sequence).upper()
    sequence = re.sub(r"\s+", "", sequence)
    sequence = re.sub(r"[^ACDEFGHIKLMNPQRSTVWY]", "X", sequence)
    return sequence


def sanitize_job_name(raw_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name.strip())
    slug = slug.strip("._-")
    return slug or "clean_job"


def read_fasta_records(fasta_path: Path) -> List[Tuple[str, str]]:
    records: List[Tuple[str, str]] = []
    current_id: Optional[str] = None
    current_seq: List[str] = []
    with fasta_path.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current_id is not None:
                    records.append((current_id, "".join(current_seq)))
                current_id = line[1:].strip() or f"record_{len(records)}"
                current_seq = []
            else:
                current_seq.append(line)
    if current_id is not None:
        records.append((current_id, "".join(current_seq)))
    return records


def load_screen_input(args: argparse.Namespace):
    import pandas as pd

    if bool(args.input_csv) == bool(args.input_fasta):
        raise ValueError("Pass exactly one of --input-csv or --input-fasta for the screen command.")

    if args.input_csv:
        input_csv = Path(args.input_csv).expanduser().resolve()
        df = pd.read_csv(input_csv)
        if args.sequence_column not in df.columns:
            raise ValueError(
                f"Sequence column '{args.sequence_column}' was not found in {input_csv}. "
                f"Available columns: {list(df.columns)}"
            )
        if "clean_row_id" not in df.columns:
            df.insert(0, "clean_row_id", range(len(df)))
        input_name = input_csv.stem
        return df, input_name, "csv"

    input_fasta = Path(args.input_fasta).expanduser().resolve()
    records = read_fasta_records(input_fasta)
    rows = [
        {"clean_row_id": index, "sequence_id": record_id, "sequence": sequence}
        for index, (record_id, sequence) in enumerate(records)
    ]
    df = pd.DataFrame(rows)
    input_name = input_fasta.stem
    return df, input_name, "fasta"


def ensure_fasta_index(python_bin: Path, fasta_path: Path) -> None:
    run(
        [
            str(python_bin),
            "-c",
            "import sys,pysam; pysam.faidx(sys.argv[1])",
            str(fasta_path),
        ]
    )


def detect_torch_runtime(python_bin: Path) -> str:
    try:
        result = run(
            [
                str(python_bin),
                "-c",
                "import torch; print('gpu' if torch.cuda.is_available() else 'cpu')",
            ],
            capture_output=True,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def run_clean_inference(
    args: argparse.Namespace,
    python_bin: Path,
    repo_dir: Path,
    fasta_path: Path,
    sequence_count: int,
) -> Path:
    app_dir = repo_dir / "app"
    results_dir = app_dir / "results" / "inputs"
    results_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    src_dir = app_dir / "src"
    env["PYTHONPATH"] = str(src_dir) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    ensure_fasta_index(python_bin, fasta_path)

    gmm_path = app_dir / "data" / "pretrained" / "gmm_ensumble.pkl"
    command = [
        str(python_bin),
        "CLEAN_inference.py",
        "--train_data",
        args.train_data,
        "--inference_fasta_folder",
        str(fasta_path.parent),
        "--inference_fasta",
        fasta_path.name,
        "--inference_fasta_start",
        "0",
        "--inference_fasta_end",
        str(sequence_count),
        "--toks_per_batch",
        str(args.toks_per_batch),
        "--esm_batches_per_clean_inference",
        str(args.esm_batches_per_clean_inference),
        "--gmm",
        str(gmm_path),
    ]
    runtime_label = detect_torch_runtime(python_bin)
    log(
        f"[2/3] CLEAN: screening {sequence_count} sequence(s) "
        f"on {runtime_label.upper()}..."
    )
    run(command, cwd=app_dir, env=env)
    fasta_stem = fasta_path.stem
    return results_dir / f"{fasta_stem}_0_{sequence_count}.csv"


def parse_prediction(raw_prediction: object) -> Tuple[str, List[str], Optional[float]]:
    if raw_prediction is None:
        return "", [], None
    text = str(raw_prediction).strip()
    if not text or text.lower() == "nan":
        return "", [], None

    ec_numbers: List[str] = []
    top_confidence: Optional[float] = None
    for index, part in enumerate(text.split(";")):
        part = part.strip()
        match = re.search(r"EC:([^/\s]+)\s*/\s*([0-9]*\.?[0-9]+)", part)
        if not match:
            continue
        ec_numbers.append(match.group(1))
        if index == 0:
            top_confidence = float(match.group(2))

    top_ec = ec_numbers[0] if ec_numbers else ""
    return top_ec, ec_numbers, top_confidence


def screen_sequences(args: argparse.Namespace) -> None:
    import pandas as pd

    work_dir = resolve_work_dir(args.work_dir)
    repo_dir = resolve_repo_dir(args, work_dir)
    python_bin = bootstrap_mode_python()
    ensure_clean_repo(args, repo_dir)
    ensure_pretrained_assets(python_bin, repo_dir, args.pretrained_url, work_dir)

    df, input_name, input_kind = load_screen_input(args)
    job_name = sanitize_job_name(args.job_name or input_name)
    temp_dir = work_dir / "jobs" / job_name
    temp_dir.mkdir(parents=True, exist_ok=True)

    if "clean_sequence_id" not in df.columns:
        df["clean_sequence_id"] = ""
    df["clean_top_confidence"] = None
    df["clean_non_enzyme_threshold"] = float(args.non_enzyme_threshold)
    df["clean_is_enzyme"] = False
    df["clean_should_run_catrange"] = False
    df["clean_status"] = ""
    df["clean_top_ec_number"] = ""
    df["clean_all_ec_numbers"] = ""
    df["clean_raw_prediction"] = ""

    sequence_records: List[Tuple[int, str, str]] = []
    if input_kind == "csv":
        raw_sequences = df[args.sequence_column]
    else:
        raw_sequences = df["sequence"]

    for row_index, raw_sequence in enumerate(raw_sequences):
        clean_row_id = int(df.iloc[row_index]["clean_row_id"])
        normalized = normalize_sequence(raw_sequence)
        sequence_id = f"row_{clean_row_id:06d}"
        df.at[row_index, "clean_sequence_id"] = sequence_id
        if not normalized:
            df.at[row_index, "clean_status"] = "empty_sequence"
            continue
        sequence_records.append((row_index, sequence_id, normalized))

    output_csv = Path(args.output_csv).expanduser().resolve()
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    if not sequence_records:
        log("[result] No non-empty sequences were provided.")
        df.to_csv(output_csv, index=False)
        if args.write_catrange_ready_csv:
            ready_path = Path(args.write_catrange_ready_csv).expanduser().resolve()
            ready_path.parent.mkdir(parents=True, exist_ok=True)
            df.iloc[0:0].to_csv(ready_path, index=False)
        return

    fasta_path = repo_dir / "app" / "data" / "inputs" / f"{job_name}.fasta"
    fasta_path.parent.mkdir(parents=True, exist_ok=True)
    with fasta_path.open("w") as handle:
        for _, sequence_id, normalized in sequence_records:
            handle.write(f">{sequence_id}\n{normalized}\n")

    results_path = run_clean_inference(args, python_bin, repo_dir, fasta_path, len(sequence_records))
    clean_df = pd.read_csv(results_path)
    prediction_by_id = {
        str(row["Seq_ID"]): row.get("Prediction", "")
        for _, row in clean_df.iterrows()
    }

    for row_index, sequence_id, _ in sequence_records:
        raw_prediction = prediction_by_id.get(sequence_id, "")
        top_ec, all_ecs, top_confidence = parse_prediction(raw_prediction)
        is_enzyme = bool(top_ec) and top_confidence is not None and top_confidence >= args.non_enzyme_threshold

        df.at[row_index, "clean_top_confidence"] = top_confidence
        df.at[row_index, "clean_raw_prediction"] = raw_prediction
        if top_ec:
            df.at[row_index, "clean_top_ec_number"] = top_ec
            df.at[row_index, "clean_all_ec_numbers"] = "; ".join(all_ecs)
        if is_enzyme:
            df.at[row_index, "clean_is_enzyme"] = True
            df.at[row_index, "clean_should_run_catrange"] = True
            df.at[row_index, "clean_status"] = "enzyme"
        elif top_ec:
            df.at[row_index, "clean_status"] = "non_enzyme_low_confidence"
        else:
            df.at[row_index, "clean_status"] = "no_prediction"

    df.to_csv(output_csv, index=False)
    enzyme_count = int(df["clean_is_enzyme"].sum())
    log(
        "[2/3] CLEAN complete: "
        f"{enzyme_count} of {len(df)} sequence(s) passed the enzyme screen."
    )

    if args.write_catrange_ready_csv:
        ready_path = Path(args.write_catrange_ready_csv).expanduser().resolve()
        ready_path.parent.mkdir(parents=True, exist_ok=True)
        ready_df = df[df["clean_should_run_catrange"]].copy()
        ready_df.to_csv(ready_path, index=False)


def merge_catrange_results(args: argparse.Namespace) -> None:
    import pandas as pd

    screened_csv = Path(args.screened_csv).expanduser().resolve()
    catrange_output_csv = Path(args.catrange_output_csv).expanduser().resolve()
    output_csv = Path(args.output_csv).expanduser().resolve()
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    screened_df = pd.read_csv(screened_csv)
    catrange_df = pd.read_csv(catrange_output_csv)

    if "clean_row_id" not in screened_df.columns:
        raise ValueError(f"{screened_csv} is missing clean_row_id.")
    if "clean_row_id" not in catrange_df.columns:
        raise ValueError(
            f"{catrange_output_csv} is missing clean_row_id. "
            "Run catrange on the --write-catrange-ready-csv output so that clean_row_id is preserved."
        )

    candidate_prediction_cols = [
        column
        for column in catrange_df.columns
        if column not in screened_df.columns or column.startswith("Predicted_")
    ]
    merged = screened_df.merge(
        catrange_df[["clean_row_id", *candidate_prediction_cols]],
        on="clean_row_id",
        how="left",
    )

    def prediction_skip_label(row: pd.Series) -> str:
        status = str(row.get("clean_status", "")).strip().lower()
        if status == "empty_sequence":
            return "skipped_empty_sequence"
        if status == "no_prediction":
            return "skipped_clean_no_prediction"
        if status == "non_enzyme_low_confidence":
            return "skipped_non_enzyme"
        return "skipped_non_enzyme"

    for column in merged.columns:
        if column.startswith("Predicted_"):
            merged[column] = merged[column].where(
                merged[column].notna(),
                merged.apply(prediction_skip_label, axis=1),
            )

    merged.to_csv(output_csv, index=False)
    log("[done] CLEAN and CatRange results combined.")


def main() -> None:
    args = parse_args()
    maybe_bootstrap_and_reexec(args)

    if args.command == "screen":
        screen_sequences(args)
    elif args.command == "merge":
        merge_catrange_results(args)
    else:
        raise ValueError(args.command)


if __name__ == "__main__":
    main()
