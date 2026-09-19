# Public data inventory and retraining prerequisites

Paths below are relative to the repository root. This inventory describes the
public export; it does not claim that the larger original research workspace
is included.

## Included directories

| Path | Contents |
| --- | --- |
| [data/raw](../raw/) | Source and curated workbooks, CSV/TSV tables, and JSON data |
| [data/raw/brenda](../raw/brenda/) | BRENDA and combined BRENDA/SABIO exports |
| [data/raw/sabio](../raw/sabio/) | SABIO kcat and KM tables |
| [data/raw/substrates](../raw/substrates/) | Substrate-to-isomeric-SMILES mappings |
| [data/catrange_metadata](./) | These notes and the final kcat ESM-C fold-5 partition workbook |
| [results/catrange](../../results/catrange/) | Saved fold summaries, holdout indices, and run manifests |
| [results/external_benchmarks](../../results/external_benchmarks/) | Saved comparator result collections |
| [benchmarks/retrained_comparators/runs](../../benchmarks/retrained_comparators/runs/) | Prepared suite inputs, predictions, evaluations, and figures |
| [ablation/runs](../../ablation/runs/) | Saved feature-ablation outputs |
| [inference/models](../../inference/models/README.md) | Inference model notes and supplied standardization statistics |

The curated workbook filenames preserve processing stages such as
`BEFOREmedian_pool`, `median_pool`, `no_OOD_nodups`, and `no_OOD_nodups_esmc`.
Select the artifact used by the experiment being reproduced rather than choosing
one by filename recency. The
[demo provenance record](../../inference/examples/demo_provenance.json) provides
specific source sheets, rows, mutations, and hashes for the demo CSVs.

## Not included: processed training tensors

This export does not contain `data/processed/`, a full `data_robust_v1/` tree,
or all trained research/comparator checkpoints. In particular, the presence of
raw workbooks and saved metrics does not make a fresh training run self-contained.

The training loader in
[catrange_model/src/data_pipeline.py](../../catrange_model/src/data_pipeline.py)
uses `CATRANGE_DATA_ROOT` when set, otherwise `data_robust_v1` relative to the
working directory. It expects two embedding-specific subdirectories under that root:

```text
data_split_curated_no_OOD_nodups_esmc/
data_split_curated_no_OOD_nodups/
```

They include aligned WT and mutant tensors, negative pools/splits, and evaluation
sets, such as `dataset_y1_y2_WT.pt`, `dataset_y1_y2_MD.pt`, and
`neg_train_dataset_y1_y2_md_drops.pt`. Consult `load_all_data` for the full required
names and their label-selection rules. Do not create replacement tensors merely
to satisfy filenames: their row alignment, feature blocks, and label meanings
are part of the experiment.

See [training instructions](../../catrange_model/README.md#training-data-prerequisite)
for configuring a data root. If the original tensors are unavailable, obtaining
or regenerating them with the original preprocessing remains a prerequisite;
this export does not provide a verified download location for that entire tree.

## Exact comparator partitions

The [partition importer](../../benchmarks/retrained_comparators/import_realkcat_partitions.py)
expects an expanded research data root containing, for example:

```text
data/processed/esmc_1152d/fold_5_kcat/fold5_partitions_and_thresholds_by_length.xlsx
data/raw/WT_MD_database_v1_curated_no_OOD_nodups_esmc.xlsx
```

That processed hierarchy is absent here. The included
[final-model partition workbook](final_model_partitions_kcat_esmc_fold5.xlsx)
is a separate exported artifact; its presence does not reconstruct every fold
or supply the importer's expected directory tree.

## Reproducibility checks

Before interpreting a rerun, compare input hashes, row identities and ordering,
fold assignments, target units, model files, configuration, and environment
versions with the saved manifest for that experiment. Apply training-derived
standardization and preserve the sequence/substrate feature split.

kcat uses eight bins in s⁻¹; KM uses six bins in M. Exact boundaries are defined
in the [inference source](../../inference/catrange_inference.py) and
[training configurations](../../catrange_model/configs/). Bins have unequal log
widths. A ±1-bin evaluation tolerance is not a confidence interval.

Historical absolute paths in saved manifests describe the machine used for the
original run. Supply paths appropriate to your checkout for a new run and keep
new outputs separate from the reference results.
