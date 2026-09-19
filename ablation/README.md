# CatRange feature ablation

These scripts compare three feature modes using the CatRange training code:

- `full`: protein and substrate/auxiliary features
- `sequence`: the first `feature_split` columns
- `substrate`: columns after that split

The ESM-C configurations set `feature_split: 1152`. This is the protein block,
not the full concatenated input dimension. The scripts use the same configured
fold procedure, seed, standardization, SMOTE, weighting, and hard-negative
mining unless an explicit ablation option changes them.

## Prerequisites

Use the [research environment](../envs/README.md) and supply the processed
training tensors described in the [data inventory](../data/catrange_metadata/DATA_DIRECTORY.md).
Those tensors are not included in this export. Set `CATRANGE_DATA_ROOT` to their
root before running the commands below:

```bash
export CATRANGE_DATA_ROOT=/path/to/data_robust_v1
```

Commands run from the repository root and set code/config/output paths explicitly.

## Run kcat

```bash
python ablation/train_catrange_ablation.py \
  --catrange-root catrange_model \
  --config catrange_model/configs/kcat_esmc.yaml \
  --output-dir ablation/runs/new_kcat_esmc_ablation \
  --device cuda

python ablation/plot_ablation_results.py \
  --results-dir ablation/runs/new_kcat_esmc_ablation \
  --dpi 600
```

Without `--feature-mode`, the training script runs all three modes. For a new
KM ablation, select the KM config and parameter for plotting:

```bash
python ablation/train_catrange_ablation.py \
  --catrange-root catrange_model \
  --config catrange_model/configs/km_esmc.yaml \
  --output-dir ablation/runs/new_km_esmc_ablation \
  --device cuda \
  --feature-mode sequence --feature-mode substrate

python ablation/plot_ablation_results.py \
  --results-dir ablation/runs/new_km_esmc_ablation \
  --parameter km --dpi 600
```

A smaller execution check can use `--device cpu --max-folds 1 --skip-hnm`.
That changes the experiment and is not a reproduction of the full ablation.
Run either script with `--help` for all supported options.

## Saved outputs and interpretation

Included runs are [kcat_esmc_ablation](runs/kcat_esmc_ablation/) and
[km_esmc_ablation](runs/km_esmc_ablation/). They contain fold metrics, summary
CSVs, manifests, and generated figures. New runs should use separate output
directories so the supplied reference results are preserved.

The [kcat manifest](runs/kcat_esmc_ablation/ablation_manifest.csv) records that
the full-feature baseline was imported from a completed CatRange CV run,
while the sequence-only and substrate-only variants were retrained. Historical
absolute paths in saved manifests identify the original run; they are not
installation instructions for another machine.

Compare modes on matching folds and metrics. A performance difference measures
the contribution of those input blocks under this training procedure; it is not
an experimental demonstration of a biochemical mechanism.
