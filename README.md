# CatRange

CatRange predicts kinetic **ranges** for enzyme–substrate pairs: catalytic turnover
(k<sub>cat</sub>, s⁻¹) and the Michaelis constant (K<sub>M</sub>, M). Inputs are a
protein sequence and substrate SMILES. The inference pipeline validates each row,
uses [CLEAN](https://github.com/tttianhao/CLEAN) to screen the protein sequence,
and predicts kinetics for eligible rows. Skipped rows remain in the output.

This repository contains the inference notebook, research code, curated data,
and saved evaluation outputs. You can also use the
[CatRange website](https://catrange.sahassbio.com).

## Run in Google Colab

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ssbio/CatRange/blob/main/CatRange_Inference_Interface.ipynb)

1. Open the notebook and sign in to Google if requested.
2. Select **Demo**, **Interactive**, **Bulk**, or **Bulk-large** in the first setup cell.
3. Keep **Mechanistic Mutation-Aware (default)** for the current ESM-C pathway;
   the notebook also exposes a legacy binary pathway for comparison.
4. Run the cells in order, review the results, and download `inference_results.csv`.

The notebook creates its runtimes and downloads dependencies and pretrained files.
Initial setup needs internet access; downloaded files can be reused while that
runtime persists. Runtime availability and duration depend on Colab.

## Run locally

Clone the repository on Linux or WSL:

```bash
git clone https://github.com/ssbio/CatRange.git
cd CatRange
```

For the guided notebook, install JupyterLab and pandas, then open
[CatRange_Inference_Interface.ipynb](CatRange_Inference_Interface.ipynb):

```bash
python3 -m pip install jupyterlab pandas
jupyter lab CatRange_Inference_Interface.ipynb
```

Install Git, curl, and unzip before running the notebook locally. Its setup creates
separate CLEAN and CatRange runtimes. A GPU is optional; model files and software
still need to be downloaded on first use.

For a scriptable CSV workflow, create a Python 3.12 environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r inference/requirements.txt
python inference/catrange_inference.py \
  --input inference/examples/demo_pairs.csv \
  --output inference_results.csv
```

The command runs **input validation → CLEAN → CatRange → merged results**.
Use `--device cpu` or `--device cuda` to select a device; the default is `auto`.
Run `python inference/catrange_inference.py --help` for other options.

CatRange weights are downloaded from [Hugging Face](https://huggingface.co/ssbio/CatRange)
as documented in the [model manifest](inference/model_manifest.json); the large
classifier files are not included in Git. CLEAN software and pretrained files
are cached in `.clean_runtime/` by default. See the
[model-file notes](inference/models/README.md).

## Inputs and demos

| Required column | Contents | Supported length |
| --- | --- | --- |
| `sequence` | Protein sequence in one-letter amino-acid codes | 9–1022 amino acids |
| `Isomeric SMILES` | Substrate SMILES | 2–512 characters |

The supplied demos have different purposes:

| Input | Rows | Purpose |
| --- | --- | --- |
| Notebook **Demo** | Two example pairs plus two deliberately invalid inputs | Demonstrate screening, prediction eligibility, and length validation |
| [demo_validation_pairs.csv](inference/examples/demo_validation_pairs.csv) | The same four input pairs as notebook Demo | Exercise those inputs through the source CLI |
| [demo_pairs.csv](inference/examples/demo_pairs.csv) | P17516 WT/Y55A and Q6FFQ0 WT/E264A+C301A | Compare WT and generated catalytic-alanine benchmark controls |

The generated variants do not establish experimentally measured mutant kinetics
or guarantee a predicted reduction. See [demo provenance](inference/examples/demo_provenance.json)
for source workbooks, mutation positions, and fixture hashes.

The notebook and CLI are separate implementations: the notebook includes mode
selection, a legacy binary pathway, batching controls, and friendly output labels;
the source CLI uses its released CatRange models and compact column names.
Identical demo input rows alone do not establish identical outputs across paths.

## Read the results

| Source column | Meaning |
| --- | --- |
| `clean_top_ec_number` | CLEAN's top EC assignment |
| `clean_top_confidence` | CLEAN score used by the screening rule |
| `clean_is_enzyme` | Whether the input passed that rule |
| `catrange_status` | Prediction status or skip reason |
| `kcat_pred_range`, `km_pred_range` | Predicted ranges, including s⁻¹ or M units |
| `kcat_confidence`, `km_confidence` | Predicted-bin model probabilities |

The notebook presents corresponding friendly column names. CLEAN screening and
model scores are computational estimates, not experimental measurements of
enzyme function or catalytic activity. Bin widths are not uniformly one decade;
the neighboring-bin guide is not a confidence interval.

## Research and reproducibility

| Directory | Included material |
| --- | --- |
| [inference](inference/) | Source inference, example inputs, and model manifest |
| [catrange_model](catrange_model/README.md) | Configured training and evaluation from precomputed features |
| [data](data/catrange_metadata/README.md) | CatLog source/curated tables and partition metadata |
| [results](results/) | Saved CatRange and comparator outputs |
| [benchmarks/retrained_comparators](benchmarks/retrained_comparators/README.md) | Comparator input preparation, training/inference runners, and evaluation |
| [ablation](ablation/README.md) | Feature-ablation scripts and saved results |
| [envs](envs/README.md) | Research environment definitions and inference runtime pins |

To create the research environments, run from the repository root:

```bash
bash scripts/env/create_conda_envs.sh all
```

Training requires the processed feature tensors expected by the data loader;
**those tensors are not included in this source/data export**. After supplying
them, set `CATRANGE_DATA_ROOT` to that tensor root; the YAML `data.root_dir` and
`dataset_version` fields are not loader overrides. A training invocation is:

```bash
conda activate catrange-notebooks-gpu
export CATRANGE_DATA_ROOT=/path/to/data_robust_v1
cd catrange_model
python -m pip install --no-deps -e .
PYTHONPATH=. python scripts/cv_train.py --config configs/kcat_esmc.yaml --device cuda
```

Use the same inputs, partitions, configuration, model files, and dependency
versions when comparing reruns. Saved manifests and metrics provide provenance;
fixed seeds alone do not guarantee bitwise equality across hardware or versions.
The [data inventory](data/catrange_metadata/DATA_DIRECTORY.md) distinguishes
included artifacts from prerequisites for a full retraining run. The
[tabular release manifest](data/RELEASE_TABULAR_MANIFEST.json) records readability,
structure, and file hashes for the exported CSV/workbook files. Run
`python tools/check_public_release.py` for the included source-release checks.


## Evolution of This Work

CatRange's range-prediction approach builds on an earlier binary-classification model
for enzyme kinetics developed by the same collaborating labs. That predecessor
codebase, **RealKcat**, is maintained separately at
[TKAI-LAB-Mali/CatRange](https://github.com/TKAI-LAB-Mali/CatRange):

> Anna Sajeevan K, Osinuga A, B A, Ferdous S, Shahreen N, Noor MS, Koneru S,
> Santos-Correa LM, Salehi R, Chowdhury NB, Calderon-Lopez B, Mali A, Saha R,
> Chowdhury R. **Robust Prediction of Enzyme Variant Kinetic Ranges with RealKcat.**
> *bioRxiv* [Preprint]. 2025 Feb 15. doi:
> [10.1101/2025.02.10.637555](https://www.biorxiv.org/content/10.1101/2025.02.10.637555v1).
> PMID: 39990461 · PMCID: PMC11844551.

## Citation

Please cite the CatRange manuscript when using this code or data:

> Sajeevan KA, Osinuga A, Arunraj B, Ferdous S, Shahreen N, Noor MS, Koneru S,
> Santos-Correa LM, Salehi R, Chowdhury NB, Aryee R, Calderon-Lopez B, Dey S,
> Mali A, Saha R, Chowdhury R. **CatRange enables robust prediction of enzyme
> variant kinetic regimes.** *PNAS Nexus*. 2026;pgag309. doi:
> [10.1093/pnasnexus/pgag309](https://doi.org/10.1093/pnasnexus/pgag309).

CatRange is a collaboration across three university labs: the
[Chowdhury Lab](https://chowdhurylab.github.io/) (Iowa State University), the
[SSBio Lab](https://sahassbio.com/) (University of Nebraska–Lincoln), and the
[TKAI Lab](https://tkai-lab-mali.github.io/) (University of South Florida).


## License

The CatRange authors' source code in this distribution is licensed under
[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and the
[retained MIT notice](LICENSES/MIT.txt) for previously MIT-declared package code.
External software, model weights, and research datasets retain their own terms;
the repository's code license does not relicense those assets.
