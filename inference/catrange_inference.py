#!/usr/bin/env python3
"""Run CLEAN screening and CatRange prediction as one inference pipeline.

The default command accepts a CSV containing protein sequences and substrate
SMILES. It runs CLEAN first, sends only enzyme-like rows to CatRange, and
writes one results CSV containing both the CLEAN screen and kinetic ranges.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable, Sequence


BIN_EDGES = {
    "kcat": (0, 1e-8, 1e-2, 1e-1, 1e0, 1e1, 1e2, 1e3, 1e8),
    "km": (1e-14, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1e4),
}

MIN_SEQUENCE_LENGTH = 9
MAX_SEQUENCE_LENGTH = 1022
MIN_SMILES_LENGTH = 2
MAX_SMILES_LENGTH = 512

joblib = None
np = None
pd = None
torch = None


def _load_runtime_dependencies() -> None:
    """Load the larger ML packages only when inference actually starts."""
    global joblib, np, pd, torch

    if all(module is not None for module in (joblib, np, pd, torch)):
        return

    try:
        import joblib as _joblib
        import numpy as _np
        import pandas as _pd
        import torch as _torch
    except ImportError as exc:
        raise RuntimeError(
            "Source inference dependencies are missing. Install them with "
            "`python -m pip install -r inference/requirements.txt`."
        ) from exc

    joblib = _joblib
    np = _np
    pd = _pd
    torch = _torch


def _log_bin_centers(parameter: str):
    _load_runtime_dependencies()
    edges = np.asarray(BIN_EDGES[parameter], dtype=float)
    safe = edges.copy()
    if safe[0] <= 0:
        safe[0] = safe[1]
    logs = np.log10(safe)
    if edges[0] <= 0:
        logs[0] = logs[1]
    centers = (logs[:-1] + logs[1:]) / 2.0
    centers[0] = logs[1]
    return centers.astype(np.float32)


def _bin_labels(parameter: str) -> list[str]:
    edges = BIN_EDGES[parameter]
    labels = []
    for low, high in zip(edges[:-1], edges[1:]):
        unit = "s^-1" if parameter == "kcat" else "M"
        labels.append(f"{low:g} to {high:g} {unit}")
    return labels


class CatRangeInference:
    """Run CatRange kcat/KM bin prediction from raw sequence and SMILES."""

    def __init__(self, models_dir: str | Path, device: str = "auto", verbose: bool = True):
        _load_runtime_dependencies()
        self.models_dir = Path(models_dir).expanduser().resolve()
        if device == "auto":
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)
        self.verbose = verbose
        self._esmc = None
        self._chem_tokenizer = None
        self._chem_model = None
        self._models: dict[str, object] = {}
        self._stats: dict[str, dict] = {}

    def _log(self, message: str) -> None:
        if self.verbose:
            print(f"      {message}", flush=True)

    def _load_esmc(self) -> None:
        if self._esmc is not None:
            return
        self._log("Loading the protein model...")
        from esm.models.esmc import ESMC

        self._esmc = ESMC.from_pretrained("esmc_600m").to(self.device)
        self._esmc.eval()

    def _load_chemberta(self) -> None:
        if self._chem_model is not None:
            return
        self._log("Loading the substrate model...")
        from transformers import AutoModel, AutoTokenizer

        repo = "seyonec/PubChem10M_SMILES_BPE_450k"
        self._chem_tokenizer = AutoTokenizer.from_pretrained(repo)
        self._chem_model = AutoModel.from_pretrained(repo).to(self.device)
        self._chem_model.eval()

    def _extract_model_archive(self) -> None:
        archive_path = self.models_dir / "model_weights.zip"
        if not zipfile.is_zipfile(archive_path):
            self._log("Downloading the CatRange model files (first run only)...")
            try:
                from huggingface_hub import hf_hub_download
            except ImportError as exc:
                raise RuntimeError(
                    "The CatRange model archive is missing and huggingface_hub "
                    "is not installed. Reinstall inference/requirements.txt."
                ) from exc
            archive_path = Path(
                hf_hub_download(
                    repo_id="ssbio/CatRange",
                    filename="model_weights.zip",
                )
            )
            if not zipfile.is_zipfile(archive_path):
                raise RuntimeError("The downloaded CatRange model archive is not a ZIP file.")

        self._log("Extracting the CatRange model files...")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        root = self.models_dir.resolve()
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                destination = (root / member.filename).resolve()
                if root not in destination.parents and destination != root:
                    raise RuntimeError(
                        f"Unsafe path in {archive_path.name}: {member.filename}"
                    )
            archive.extractall(root)

    def _find_model_path(self, parameter: str) -> Path:
        candidates = (
            self.models_dir / f"{parameter}_esmc_FINAL.pkl",
            self.models_dir / f"{parameter}_model_v1b.pkl",
            self.models_dir / "model_weights" / f"{parameter}_model_v1b.pkl",
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate

        self._extract_model_archive()
        for candidate in candidates:
            if candidate.exists():
                return candidate

        raise FileNotFoundError(
            f"The {parameter} CatRange model was not found in {self.models_dir}. "
            "Place the released .pkl model files in inference/models/."
        )

    def _load_model(self, parameter: str) -> None:
        parameter = parameter.lower()
        if parameter in self._models:
            return

        model_path = self._find_model_path(parameter)
        stats_path = self.models_dir / f"{parameter}_esmc_FINAL_stats.pt"
        self._models[parameter] = joblib.load(model_path)
        if stats_path.exists():
            self._stats[parameter] = torch.load(
                stats_path, map_location="cpu", weights_only=False
            )
        else:
            self._stats[parameter] = {}

    def embed_sequence(self, sequence: str):
        self._load_esmc()
        from esm.sdk.api import ESMProtein, LogitsConfig

        sequence = str(sequence).strip().upper()
        with torch.no_grad():
            protein = ESMProtein(sequence=sequence)
            tokens = self._esmc.encode(protein)
            out = self._esmc.logits(
                tokens,
                LogitsConfig(sequence=True, structure=True, return_embeddings=True),
            )
            reps = out.embeddings[0, 1 : len(sequence) + 1].float()
        return reps.mean(dim=0).cpu().numpy().astype(np.float32)

    def embed_smiles(self, smiles: str):
        self._load_chemberta()
        inputs = self._chem_tokenizer(
            [str(smiles).strip()],
            return_tensors="pt",
            padding=True,
            truncation=False,
        )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with torch.no_grad():
            out = self._chem_model(**inputs)
        return out.last_hidden_state[0].float().mean(dim=0).cpu().numpy().astype(np.float32)

    def embed_pairs(self, pairs: Iterable[tuple[str, str]]):
        seq_embeddings = []
        smiles_embeddings = []
        for sequence, smiles in pairs:
            seq_embeddings.append(self.embed_sequence(sequence))
            smiles_embeddings.append(self.embed_smiles(smiles))
        return np.stack(seq_embeddings), np.stack(smiles_embeddings)

    def _standardize(self, parameter: str, seq_embeddings, smiles_embeddings):
        stats = self._stats.get(parameter, {})
        mean_1 = float(stats.get("mean_1", 0.0))
        std_1 = max(float(stats.get("std_1", 1.0)), 1e-8)
        mean_2 = float(stats.get("mean_2", 0.0))
        std_2 = max(float(stats.get("std_2", 1.0)), 1e-8)
        seq = (seq_embeddings - mean_1) / std_1
        sub = (smiles_embeddings - mean_2) / std_2
        return np.concatenate([seq, sub], axis=1).astype(np.float32)

    def predict_from_embeddings(
        self,
        seq_embeddings,
        smiles_embeddings,
        parameter: str = "kcat",
    ):
        parameter = parameter.lower()
        if parameter not in BIN_EDGES:
            raise ValueError("parameter must be 'kcat' or 'km'")
        self._load_model(parameter)
        x = self._standardize(parameter, seq_embeddings, smiles_embeddings)
        model = self._models[parameter]
        if hasattr(model, "predict_proba"):
            probs = model.predict_proba(x)
            pred_bin = probs.argmax(axis=1)
            confidence = probs.max(axis=1)
        else:
            pred_bin = model.predict(x).astype(int)
            probs = np.full((len(pred_bin), len(BIN_EDGES[parameter]) - 1), np.nan)
            confidence = np.full(len(pred_bin), np.nan)
        centers = _log_bin_centers(parameter)
        expected_log10 = (
            probs @ centers
            if np.isfinite(probs).all()
            else np.full(len(pred_bin), np.nan)
        )
        labels = _bin_labels(parameter)
        out = pd.DataFrame(
            {
                f"{parameter}_pred_bin": pred_bin.astype(int),
                f"{parameter}_pred_range": [labels[int(i)] for i in pred_bin],
                f"{parameter}_confidence": confidence,
                f"{parameter}_expected_log10": expected_log10,
            }
        )
        for index in range(probs.shape[1]):
            out[f"{parameter}_prob_{index}"] = probs[:, index]
        return out

    def predict(self, pairs: Iterable[tuple[str, str]], parameter: str = "kcat"):
        pairs = list(pairs)
        seq_embeddings, smiles_embeddings = self.embed_pairs(pairs)
        out = self.predict_from_embeddings(
            seq_embeddings, smiles_embeddings, parameter=parameter
        )
        out.insert(0, "smiles", [smiles for _, smiles in pairs])
        out.insert(0, "sequence", [sequence for sequence, _ in pairs])
        return out


def _input_status(sequence: str, smiles: str) -> str:
    if not sequence:
        return "empty_sequence"
    if len(sequence) < MIN_SEQUENCE_LENGTH:
        return "sequence_too_short"
    if len(sequence) > MAX_SEQUENCE_LENGTH:
        return "sequence_too_long"
    if not smiles:
        return "empty_smiles"
    if len(smiles) < MIN_SMILES_LENGTH:
        return "smiles_too_short"
    if len(smiles) > MAX_SMILES_LENGTH:
        return "smiles_too_long"
    return "ready"


def load_inference_input(input_csv: str | Path):
    """Read and validate the student-facing sequence/SMILES CSV."""
    _load_runtime_dependencies()
    input_path = Path(input_csv).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    frame = pd.read_csv(input_path)
    if frame.empty:
        raise ValueError("The input CSV has no data rows.")
    if "sequence" not in frame.columns:
        raise ValueError("The input CSV needs a column named 'sequence'.")

    if "Isomeric SMILES" not in frame.columns:
        if "smiles" in frame.columns:
            frame["Isomeric SMILES"] = frame["smiles"]
        else:
            raise ValueError(
                "The input CSV needs an 'Isomeric SMILES' column "
                "(a 'smiles' column is also accepted)."
            )

    if "clean_row_id" in frame.columns:
        frame = frame.drop(columns=["clean_row_id"])
    frame.insert(0, "clean_row_id", range(len(frame)))
    frame["sequence"] = (
        frame["sequence"]
        .fillna("")
        .astype(str)
        .str.replace(r"\s+", "", regex=True)
        .str.upper()
        .str.replace(r"[^ACDEFGHIKLMNPQRSTVWY]", "X", regex=True)
    )
    frame["Isomeric SMILES"] = (
        frame["Isomeric SMILES"]
        .fillna("")
        .astype(str)
        .str.replace(r"\s+", "", regex=True)
    )
    frame["input_status"] = [
        _input_status(sequence, smiles)
        for sequence, smiles in zip(frame["sequence"], frame["Isomeric SMILES"])
    ]
    return frame


def run_clean_screen(
    input_csv: str | Path,
    screened_csv: str | Path,
    ready_csv: str | Path,
    *,
    work_dir: str | Path,
    non_enzyme_threshold: float = 0.5,
    clean_repo_dir: str | Path | None = None,
    verbose: bool = False,
) -> None:
    """Run the bundled CLEAN module in its isolated environment."""
    clean_script = Path(__file__).with_name("clean_inference.py")
    if not clean_script.exists():
        raise FileNotFoundError(f"CLEAN module not found: {clean_script}")

    command = [
        sys.executable,
        str(clean_script),
        "--work-dir",
        str(Path(work_dir).expanduser().resolve()),
        "--non-enzyme-threshold",
        str(non_enzyme_threshold),
    ]
    if clean_repo_dir is not None:
        command.extend(
            ["--clean-repo-dir", str(Path(clean_repo_dir).expanduser().resolve())]
        )
    if verbose:
        command.append("--verbose")
    command.extend(
        [
            "screen",
            "--input-csv",
            str(Path(input_csv).expanduser().resolve()),
            "--sequence-column",
            "sequence",
            "--output-csv",
            str(Path(screened_csv).expanduser().resolve()),
            "--write-catrange-ready-csv",
            str(Path(ready_csv).expanduser().resolve()),
            "--job-name",
            "catrange_source_inference",
        ]
    )
    subprocess.run(command, check=True)


def _catrange_status(row) -> str:
    if row.get("input_status") != "ready":
        return f"skipped_{row.get('input_status')}"
    clean_status = str(row.get("clean_status", "")).strip().lower()
    if clean_status == "enzyme":
        return "predicted"
    if clean_status == "no_prediction":
        return "skipped_clean_no_prediction"
    if clean_status == "empty_sequence":
        return "skipped_empty_sequence"
    return "skipped_non_enzyme"


def run_inference_pipeline(
    input_csv: str | Path,
    output_csv: str | Path,
    *,
    models_dir: str | Path,
    parameters: Sequence[str] = ("kcat", "km"),
    device: str = "auto",
    clean_work_dir: str | Path = ".clean_runtime",
    clean_threshold: float = 0.5,
    clean_repo_dir: str | Path | None = None,
    verbose: bool = True,
):
    """Run input checks, CLEAN screening, and CatRange prediction."""
    _load_runtime_dependencies()
    if not 0 <= clean_threshold <= 1:
        raise ValueError("clean_threshold must be between 0 and 1.")
    invalid_parameters = sorted(set(parameters) - set(BIN_EDGES))
    if invalid_parameters:
        raise ValueError(
            "Unknown parameter(s): " + ", ".join(invalid_parameters)
        )

    output_path = Path(output_csv).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    input_frame = load_inference_input(input_csv)
    valid_input = input_frame[input_frame["input_status"] == "ready"].copy()

    print(
        f"[1/3] Input ready: {len(valid_input)} of {len(input_frame)} row(s) valid.",
        flush=True,
    )

    with tempfile.TemporaryDirectory(
        prefix="catrange-inference-", dir=output_path.parent
    ) as temporary_directory:
        temporary_path = Path(temporary_directory)
        clean_input_path = temporary_path / "clean_input.csv"
        screened_path = temporary_path / "clean_screened.csv"
        ready_path = temporary_path / "clean_catrange_ready.csv"

        if valid_input.empty:
            screened = input_frame.copy()
            screened["clean_status"] = screened["input_status"]
            screened["clean_is_enzyme"] = False
            screened["clean_should_run_catrange"] = False
            screened["clean_top_ec_number"] = ""
            screened["clean_top_confidence"] = np.nan
        else:
            valid_input.to_csv(clean_input_path, index=False)
            run_clean_screen(
                clean_input_path,
                screened_path,
                ready_path,
                work_dir=clean_work_dir,
                non_enzyme_threshold=clean_threshold,
                clean_repo_dir=clean_repo_dir,
                verbose=verbose,
            )
            screened_valid = pd.read_csv(screened_path)
            invalid_input = input_frame[
                input_frame["input_status"] != "ready"
            ].copy()
            if not invalid_input.empty:
                invalid_input["clean_status"] = invalid_input["input_status"]
                invalid_input["clean_is_enzyme"] = False
                invalid_input["clean_should_run_catrange"] = False
                invalid_input["clean_top_ec_number"] = ""
                invalid_input["clean_top_confidence"] = np.nan
            screened = pd.concat(
                [screened_valid, invalid_input], ignore_index=True, sort=False
            ).sort_values("clean_row_id")

        ready = screened[screened["clean_should_run_catrange"] == True].copy()  # noqa: E712
        if ready.empty:
            final = screened.copy()
            for parameter in parameters:
                final[f"{parameter}_pred_bin"] = np.nan
                final[f"{parameter}_pred_range"] = ""
                final[f"{parameter}_confidence"] = np.nan
                final[f"{parameter}_expected_log10"] = np.nan
                for index in range(len(BIN_EDGES[parameter]) - 1):
                    final[f"{parameter}_prob_{index}"] = np.nan
            print("[3/3] CatRange skipped: no rows passed the CLEAN screen.", flush=True)
        else:
            print(
                f"[3/3] CatRange: predicting kinetics for {len(ready)} row(s)...",
                flush=True,
            )
            predictor = CatRangeInference(
                models_dir=models_dir, device=device, verbose=verbose
            )
            pairs = list(zip(ready["sequence"], ready["Isomeric SMILES"]))
            sequence_embeddings, smiles_embeddings = predictor.embed_pairs(pairs)
            predictions = ready[["clean_row_id"]].reset_index(drop=True)
            for parameter in parameters:
                parameter_predictions = predictor.predict_from_embeddings(
                    sequence_embeddings,
                    smiles_embeddings,
                    parameter=parameter,
                ).reset_index(drop=True)
                predictions = pd.concat(
                    [predictions, parameter_predictions], axis=1
                )
            final = screened.merge(predictions, on="clean_row_id", how="left")

        final["catrange_status"] = final.apply(_catrange_status, axis=1)
        final = final.sort_values("clean_row_id").reset_index(drop=True)
        final.to_csv(output_path, index=False)

    predicted_count = int((final["catrange_status"] == "predicted").sum())
    print(
        f"[done] Saved {predicted_count} prediction(s) to {output_path}",
        flush=True,
    )
    return final


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run CLEAN enzyme screening and CatRange kinetic-range prediction "
            "from one CSV file."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        help="CSV containing 'sequence' and 'Isomeric SMILES' columns.",
    )
    parser.add_argument(
        "--output",
        default="inference_results.csv",
        help="Results CSV (default: inference_results.csv).",
    )
    parser.add_argument(
        "--models-dir",
        default=str(Path(__file__).resolve().parent / "models"),
        help="Directory containing the released CatRange model files.",
    )
    parser.add_argument(
        "--parameter",
        choices=("both", "kcat", "km"),
        default="both",
        help="Kinetic parameter to predict (default: both).",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
        help="Computation device (default: auto).",
    )
    parser.add_argument(
        "--clean-work-dir",
        default=".clean_runtime",
        help="Reusable directory for CLEAN software and model files.",
    )
    parser.add_argument(
        "--clean-threshold",
        type=float,
        default=0.5,
        help="Minimum CLEAN confidence for enzyme-like input (default: 0.5).",
    )
    parser.add_argument(
        "--clean-repo-dir",
        default=None,
        help="Optional path to an existing CLEAN checkout.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Hide optional model-loading details.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    parameters = ("kcat", "km") if args.parameter == "both" else (args.parameter,)
    try:
        run_inference_pipeline(
            args.input,
            args.output,
            models_dir=args.models_dir,
            parameters=parameters,
            device=args.device,
            clean_work_dir=args.clean_work_dir,
            clean_threshold=args.clean_threshold,
            clean_repo_dir=args.clean_repo_dir,
            verbose=not args.quiet,
        )
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"\nCatRange could not finish: {exc}\n")


if __name__ == "__main__":
    main()
