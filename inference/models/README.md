# CatRange inference model files

The large trained classifier files are hosted on
[Hugging Face](https://huggingface.co/ssbio/CatRange), not committed to this Git
repository. The [source inference script](../catrange_inference.py) downloads the
archive documented in [model_manifest.json](../model_manifest.json) when required.

It recognizes these classifier names:

```text
kcat_esmc_FINAL.pkl
km_esmc_FINAL.pkl
```

The released archive can instead provide `kcat_model_v1b.pkl` and
`km_model_v1b.pkl`; the loader recognizes those names. This directory also
contains the supplied standardization-stat files:

```text
kcat_esmc_FINAL_stats.pt
km_esmc_FINAL_stats.pt
```

Keep classifier files and preprocessing statistics matched. Use `--models-dir`
to select another model directory. The CLEAN runtime and pretrained assets use
a separate cache, selected by `--clean-work-dir`.

The [notebook](../../CatRange_Inference_Interface.ipynb) manages its own working
directories and offers mechanistic and legacy binary pathways. Record the chosen
pathway and downloaded model versions when reproducing a run. See the
[root instructions](../../README.md#inputs-and-demos) for the distinct demos.
