# CatRange

CatRange predicts useful **ranges** for two enzyme kinetic parameters:

- **k<sub>cat</sub>** — how quickly an enzyme converts substrate to product
- **K<sub>M</sub>** — the substrate concentration associated with half-maximal reaction speed

You provide a protein sequence and a substrate SMILES string. The pipeline first uses
[CLEAN](https://github.com/tttianhao/CLEAN) to check whether the sequence is enzyme-like,
then runs CatRange only for rows that pass that screen.

<h2 align="center">Run CatRange in Google Colab</h2>

<p align="center">
  <a href="https://colab.research.google.com/github/ssbio/CatRange/blob/main/CatRange_Inference_Interface.ipynb">
    <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open CatRange in Google Colab" height="42">
  </a>
</p>

<p align="center"><strong>RECOMMENDED FOR MOST USERS</strong><br><strong>No installation or coding required</strong></p>

> **Model weights:** CatRange downloads its model weights automatically from
> [Hugging Face](https://huggingface.co/ssbio/CatRange). The model weights are
> not stored in this Git repository.

## Google Colab: Quick Start

1. Click the **Open in Colab** badge above.
2. Sign in to Google if asked.
3. In Colab, choose **Runtime → Run all**.
4. Keep **Demo** selected for your first run.
5. Review the results table and download `inference_results.csv`.

The notebook installs its own compatible software versions. The first run takes longer
because it downloads the models; later runs in the same runtime reuse those files.

## Choose How You Want to Run CatRange

| Method | Best for | Setup level |
| --- | --- | --- |
| [Google Colab](#method-1-google-colab-recommended) | First-time users, classes, and quick tests | None |
| [Local Jupyter notebook](#method-2-local-jupyter-notebook) | Working on your own Linux/WSL computer | Basic |
| [Source-code command](#method-3-source-code-command) | Automation, scripts, and advanced use | Advanced |

## What You Need

Each input row needs two columns:

| Column | What to enter | Example |
| --- | --- | --- |
| `sequence` | A protein amino-acid sequence using one-letter codes | `MKT...` |
| `Isomeric SMILES` | The substrate's isomeric SMILES string | `CCO` |

You can start with [`inference/examples/demo_pairs.csv`](inference/examples/demo_pairs.csv).

Supported input sizes:

- Protein sequence: 9–1022 amino acids
- Isomeric SMILES: 2–512 characters

## How to Run Inference

### Method 1: Google Colab (recommended)

Use this method if you want the simplest experience.

1. Open the [CatRange inference notebook in Colab](https://colab.research.google.com/github/ssbio/CatRange/blob/main/CatRange_Inference_Interface.ipynb).
2. Choose an input mode:
   - **Demo** uses included example data.
   - **Interactive** asks for one or more sequence/SMILES pairs.
   - **Bulk** uploads a CSV.
   - **Bulk-large** processes a larger CSV in batches.
3. Keep **Mechanistic Mutation-Aware** selected unless you are reproducing an older benchmark.
4. Run the cells from top to bottom.
5. Download `inference_results.csv` from the final cell.

Colab automatically performs these steps:

1. Checks the input format and length limits.
2. Runs the CLEAN enzyme screen.
3. Predicts k<sub>cat</sub> and K<sub>M</sub> ranges for enzyme-like rows.
4. Combines everything into one results table.

### Method 2: Local Jupyter notebook

Use this method to run the same guided interface on your own computer. The local
workflow currently requires Linux or Windows Subsystem for Linux (WSL). A GPU is
helpful but not required.

> The notebook runs locally, but the first setup still needs internet access to download
> software and model files. Cached files can be reused for later runs.

1. Install Git, Python 3, and Jupyter.
2. Clone the repository:

   ```bash
   git clone https://github.com/ssbio/CatRange.git
   cd CatRange
   ```

3. Install the lightweight notebook launcher requirements:

   ```bash
   python3 -m pip install jupyter pandas
   ```

4. Open the provided notebook:

   ```bash
   jupyter lab CatRange_Inference_Interface.ipynb
   ```

5. Choose **Demo** for a first run, then run the cells from top to bottom.

The notebook creates isolated runtimes for CLEAN and CatRange, which prevents their
machine-learning dependencies from interfering with each other.

### Method 3: Source-code command

Use this method for repeatable scripts or batch jobs. It currently requires Linux or
WSL and Python 3.12.

1. Clone the repository:

   ```bash
   git clone https://github.com/ssbio/CatRange.git
   cd CatRange
   ```

2. Create an environment and install the source inference requirements:

   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -r inference/requirements.txt
   ```

3. Run the demo CSV:

   ```bash
   python inference/catrange_inference.py \
     --input inference/examples/demo_pairs.csv \
     --output inference_results.csv
   ```

That single command runs **input validation → CLEAN → CatRange → merged results**.
There is no separate cleaning command to remember. The CLEAN environment, source, and
pretrained files are downloaded automatically on the first run and cached in
`.clean_runtime/`. CatRange model weights are downloaded from
[Hugging Face](https://huggingface.co/ssbio/CatRange), not from this Git repository.

For all command options:

```bash
python inference/catrange_inference.py --help
```

## Understanding the Results

The Colab notebook uses friendly column names; the source command uses compact
machine-friendly names.

| Colab column | Source column | Meaning |
| --- | --- | --- |
| `Predicted EC number` | `clean_top_ec_number` | CLEAN's most likely EC number |
| `clean_top_confidence` | `clean_top_confidence` | CLEAN's confidence score for its top EC prediction |
| `Classified as enzyme?` | `clean_is_enzyme` | Whether the row passed the CLEAN enzyme screen |
| `Pipeline note` | `catrange_status` | Whether CatRange predicted the row or why it was skipped |
| `Predicted kcat range (s^-1)` | `kcat_pred_range` | Predicted k<sub>cat</sub> range |
| `Predicted KM range (M)` | `km_pred_range` | Predicted K<sub>M</sub> range |

The CLEAN confidence is a model score, not an experimental measurement. CatRange
reports ranges because enzyme measurements can vary substantially with experimental
conditions.

## For Researchers and Developers

CatRange combines ESM-C protein embeddings, ChemBERTa substrate embeddings, and
XGBoost classification. The CatLog curated enzyme-kinetics data support model training,
benchmarking, and manuscript analyses.

### Repository layout

```text
CatRange_Inference_Interface.ipynb  Guided Colab/local inference notebook
inference/                          End-to-end source inference and model files
catrange_model/                     CatRange training and evaluation code
data/                               CatLog/CatRange data and metadata
results/                            CatRange and comparator benchmark outputs
benchmarks/retrained_comparators/   Comparator retraining scripts
ablation/                           Feature-ablation scripts and results
figures/                            Figure source and output files
manuscript/                         Manuscript and supporting information
envs/                               Reproducible environment definitions
```

### Train CatRange

Create the research environments:

```bash
bash scripts/env/create_conda_envs.sh all
```

Run a manuscript configuration:

```bash
cd catrange_model
python3 -m pip install --no-deps -e .
PYTHONPATH=. python scripts/cv_train.py --config configs/kcat_esmc.yaml --device cuda
```

See [`envs/README.md`](envs/README.md) and
[`catrange_model/README.md`](catrange_model/README.md) for training, benchmarking, and
reproducibility details.

## Citation

Please cite the CatRange manuscript when using this code or data.
