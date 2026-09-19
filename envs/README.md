# CatRange environments

These files describe research environments for training, feature generation,
notebook analysis, and plotting. The inference notebook manages its own isolated
runtimes; the source CLI uses [inference/requirements.txt](../inference/requirements.txt).
Do not combine these dependency sets without checking compatibility.

| Environment | Definition | Purpose |
| --- | --- | --- |
| `catrange-notebooks-gpu` | [catrange-notebooks-gpu.yml](catrange-notebooks-gpu.yml) | Research notebooks, training/evaluation, XGBoost, ESM-2, and benchmark analysis |
| `catrange-esmc-gpu` | [catrange-esmc-gpu.yml](catrange-esmc-gpu.yml) | ESM-C protein feature generation |
| `catrange-chemberta-gpu` | [catrange-chemberta-gpu.yml](catrange-chemberta-gpu.yml) | ChemBERTa substrate feature generation |
| `catrange-cpu-figures` | [catrange-cpu-figures.yml](catrange-cpu-figures.yml) | CPU plotting and table analysis |

The research GPU definitions specify `pytorch-cuda=11.8`. ESM-C and ChemBERTa
research environments are separated to avoid dependency conflicts; their saved
features can then be used in the training environment.

## Create and verify

Run from the repository root with conda available:

```bash
bash scripts/env/create_conda_envs.sh all
# Or select one environment:
bash scripts/env/create_conda_envs.sh notebooks-gpu
bash scripts/env/create_conda_envs.sh esmc-gpu
bash scripts/env/create_conda_envs.sh chemberta-gpu
bash scripts/env/create_conda_envs.sh figures-cpu
```

The helper creates missing environments and may update an existing environment
of the same name. Inspect [create_conda_envs.sh](../scripts/env/create_conda_envs.sh)
before using it with an environment that contains other work.

```bash
bash scripts/env/verify_conda_envs.sh
```

Register a Jupyter kernel when needed:

```bash
conda run -n catrange-notebooks-gpu python -m ipykernel install --user \
  --name catrange-notebooks-gpu --display-name "CatRange notebooks GPU"
```

Use the corresponding environment name for ESM-C or ChemBERTa kernels.
Environment creation does not obtain the external training tensors or comparator
checkpoints; see the [data inventory](../data/catrange_metadata/DATA_DIRECTORY.md).

## Notebook runtime pins

The notebook's separate runtime requirements are recorded in:

- [colab-clean-py312.txt](colab-clean-py312.txt)
- [colab-catrange-mechanistic-py312.txt](colab-catrange-mechanistic-py312.txt)
- [colab-catrange-binary-py310.txt](colab-catrange-binary-py310.txt)

The Python version, runtime pathway, and model files are part of the inference
provenance. The legacy binary pathway is not interchangeable with the default
mechanistic ESM-C pathway.
