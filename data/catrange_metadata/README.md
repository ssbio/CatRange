# CatLog and CatRange data

The public data export contains curated/source tables in [data/raw](../raw/)
and the [final kcat ESM-C fold-5 partition workbook](final_model_partitions_kcat_esmc_fold5.xlsx)
in this directory. These accompany the training code and saved evaluations;
they are not a complete copy of the original tensor workspace.

## Included materials

- [BRENDA-derived tables](../raw/brenda/) and [SABIO-derived tables](../raw/sabio/)
- [Substrate-to-SMILES mappings](../raw/substrates/)
- Curated WT/mutant workbook versions under [data/raw](../raw/)
- [PafA curated measurements](../raw/PafA_1_curated_v1.csv) and
  [PafA partition metadata](../raw/PafA_partitions_metadata.xlsx)
- The final-model partition workbook linked above

The [inventory and usage notes](DATA_DIRECTORY.md) explain the external files
needed for retraining. Model metrics and historical run manifests are under
[results](../../results/) and the
[comparator suite](../../benchmarks/retrained_comparators/README.md).

The [release manifest](../RELEASE_TABULAR_MANIFEST.json) records structural checks
and hashes for 248 CSV/workbook files (239 CSVs and nine workbooks). Its scope is
readability and file integrity, not scientific validation or proof that every
original research artifact is present.

## Preserve provenance

Keep the source workbook/version, sheet, row identity, units, and preprocessing
steps with derived datasets. WT, mutant, PafA, OOD, and negative-pool artifacts
have distinct roles; filenames alone do not establish that their labels or
partitions are interchangeable.

Training features concatenate a protein block (1152 columns for ESM-C or 1280
for ESM-2) with substrate/auxiliary features. The total model input is wider
than the protein block. Use the matching model, feature order, and training
standardization statistics.

The raw-sequence inference workflow does not require downloading the research
training tensors. See the [inference quick start](../../README.md#run-locally).
