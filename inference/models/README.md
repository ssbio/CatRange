# CatRange Model Files

The trained CatRange XGBoost models are too large for normal GitHub storage.
The notebook and `inference/catrange_inference.py` download the released model
archive from Hugging Face and extract it automatically when needed.

Expected files:

```text
kcat_esmc_FINAL.pkl
km_esmc_FINAL.pkl
```

Optional standardization-stat files:

```text
kcat_esmc_FINAL_stats.pt
km_esmc_FINAL_stats.pt
```

The source script also recognizes the `kcat_model_v1b.pkl` and
`km_model_v1b.pkl` names inside the released archive.
