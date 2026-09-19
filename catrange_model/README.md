# CatRange: Robust Prediction of Enzyme Variant Kinetic Ranges

This package trains and evaluates CatRange classifiers from **precomputed
protein and substrate features**. For raw protein sequence + SMILES inference,
use the [repository quick start](../README.md#run-locally) or
[Colab notebook](../CatRange_Inference_Interface.ipynb).

## Install

From the repository root, create and activate the research environment:

```bash
bash scripts/env/create_conda_envs.sh notebooks-gpu
conda activate catrange-notebooks-gpu
cd catrange_model
python -m pip install --no-deps -e .
```

Alternatively, this directory includes separate
[CPU](CatRange_env_cpu.yml) and [GPU](CatRange_env_gpu.yml) conda definitions
with matching [CPU requirements](requirements_cpu.txt) and
[GPU requirements](requirements_gpu.txt). Use a consistent environment rather
than combining dependency sets. See [environment notes](../envs/README.md).

The package registers `catrange-train` and `catrange-predict`.
The `realkcat-train` and `realkcat-predict` aliases remain for existing scripts.

```bash
catrange-train --help
catrange-predict --help
```

## Training data prerequisite

The training tensors are **not included in this export**. The loader expects
an external tensor tree containing these embedding-specific folders:

- `data_split_curated_no_OOD_nodups_esmc`
- `data_split_curated_no_OOD_nodups`

The required WT, mutant, negative, and evaluation tensors are enumerated by
[`load_all_data`](src/data_pipeline.py). They must retain their original row
alignment, labels, and partition provenance. YAML `data.root_dir` and
`dataset_version` entries are not loader overrides. Select the tensor root with:

```bash
export CATRANGE_DATA_ROOT=/path/to/data_robust_v1
```

If this variable is unset, the loader uses `data_robust_v1` relative to the
working directory. See the [data inventory](../data/catrange_metadata/DATA_DIRECTORY.md)
for missing prerequisites.

## Train

Run commands in this directory after supplying the required data:

| Configuration | Target | Protein-feature block |
| --- | --- | --- |
| [kcat_esmc.yaml](configs/kcat_esmc.yaml) | k<sub>cat</sub> | ESM-C, 1152 columns |
| [km_esmc.yaml](configs/km_esmc.yaml) | K<sub>M</sub> | ESM-C, 1152 columns |
| [kcat_esm2.yaml](configs/kcat_esm2.yaml) | k<sub>cat</sub> | ESM-2, 1280 columns |
| [km_esm2.yaml](configs/km_esm2.yaml) | K<sub>M</sub> | ESM-2, 1280 columns |

Substrate/auxiliary features follow that protein block; those dimensions do not
describe the entire concatenated model input.

```bash
catrange-train --config configs/kcat_esmc.yaml --device cuda
# Equivalent source entry point:
PYTHONPATH=. python scripts/cv_train.py --config configs/kcat_esmc.yaml --device cuda
```

Use `--device cpu` for CPU execution. Configurations specify five folds, seed 42,
SMOTE, class weighting, and hard-negative-mining settings. The kcat ESM-C
configuration uses 1920 estimators and a maximum depth of 11; consult each YAML
for its complete parameter set rather than assuming all experiments share one set.

Outputs go under `outputs/<parameter>_<embedding>/`, including models, fold
metrics, holdout indices, and a training manifest. `--output-dir` chooses another
parent directory. `--final-fold` defaults to 5 and selects the saved fold model
copied to the `FINAL` model filename.

## Inference

For raw sequences and SMILES, use the separate Python 3.12 inference environment
described in the [root README](../README.md#run-locally):

```bash
python ../inference/catrange_inference.py \
  --input ../inference/examples/demo_pairs.csv \
  --output inference_results.csv
```

The package command instead accepts precomputed concatenated features:

```bash
catrange-predict \
  --model outputs/kcat_esmc/models/kcat_esmc_fold5.pkl \
  --features /path/to/concatenated_embeddings.pt \
  --output predictions.csv
```

Match feature ordering and preprocessing to the selected model. Protein-block
dimensions, substrate features, and standardization statistics must agree.
Do not substitute ESM-2 tensors into an ESM-C model.

## Reproducibility

Keep the exact input tensors, row order, partition assignments, configuration,
dependency versions, and hardware details with each run. The code uses seed 42
and deterministic settings where supported, but those settings do not establish
bitwise equality across software versions or devices.

For an independent rerun comparison, use separate output directories:

```bash
catrange-train --config configs/kcat_esmc.yaml --device cpu --output-dir reruns/run_a
catrange-train --config configs/kcat_esmc.yaml --device cpu --output-dir reruns/run_b
diff reruns/run_a/kcat_esmc/results/kcat_esmc_crossval_summary.csv \
     reruns/run_b/kcat_esmc/results/kcat_esmc_crossval_summary.csv
```

A matching summary verifies that comparison only; also inspect manifests,
holdout identities, and per-fold outputs for the experiment being reproduced.
Saved reference artifacts are under [results/catrange](../results/catrange/).


## 📚 Citation

If you use **CatRange** in your work, please cite the following:

> 🧬 Anna Sajeevan K, Osinuga A, B A, Ferdous S, Shahreen N, Noor MS, Koneru S, Santos-Correa LM, Salehi R, Chowdhury NB, Aryee R,Calderon-Lopez B, Mali A, Saha R, Chowdhury R.  
> **Robust Prediction of Enzyme Variant Kinetic Ranges with RealKcat**<br>
> *bioRxiv* [Preprint], 2025 Feb 15. doi: [10.1101/2025.02.10.637555](https://www.biorxiv.org/content/10.1101/2025.02.10.637555v1)<br>
> PMID: 39990461 · PMCID: PMC11844551


<details>
<summary>📄 BibTeX</summary>

```bibtex
@article{sajeevan2025robust,
  author = {Sajeevan, Anna K and Osinuga, Abraham and B, A and Ferdous, Sakib and Shahreen, Nabia and Noor, Mohammed Sakib and Koneru, Shashank and Santos-Correa, Laura Mariana and Salehi, Rahil and Chowdhury, Niaz Bahar and Aryee, Randy and Calderon-Lopez, Brisa and Mali, Ankur and Saha, Rajib and Chowdhury, Ratul},
  title = {Robust Prediction of Enzyme Variant Kinetic Ranges with RealKcat},
  journal = {bioRxiv},
  year = {2025},
  month = {Feb},
  day = {15},
  note = {Preprint},
  doi = {10.1101/2025.02.10.637555},
  pmid = {39990461},
  pmcid = {PMC11844551}
}
```
</details>


## License

The CatRange authors' source code in this package is licensed under
[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and the
[retained MIT notice](LICENSES/MIT.txt) for previously MIT-declared package code.
External software, model weights, and research datasets retain their own terms;
the package's code license does not relicense those assets.
