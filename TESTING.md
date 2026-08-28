# Colab Python runtime stability test

This branch isolates every dependency stack from Colab's launcher Python:

- CLEAN uses a `uv`-managed Python 3.12 environment.
- Mechanistic CatRange / ESM-C uses a separate managed Python 3.12 environment.
- Binary CatRange / ESM-2 uses a separate managed Python 3.10 environment.

The notebook may itself launch under Python 3.13 or a later Colab default. It no
longer uses the launcher interpreter to create any model environment, and it does
not depend on Ubuntu's version-specific `python3.x-venv` packages or `get-pip.py`.

## Colab test matrix

1. Open `CatRange_Inference_Interface.ipynb` from this branch in a fresh GPU runtime.
2. Run the setup cell and the pipeline in the default mechanistic mode.
3. Confirm the log reports managed Python 3.12 for CLEAN and mechanistic inference.
4. Rerun the pipeline and confirm both environments are reused after validation.
5. Delete `/content/.clean_runtime/clean_env/.bootstrap_complete`, rerun, and confirm
   the incomplete CLEAN environment is rebuilt automatically.
6. Restart the runtime, select Binary Alanine Simplified mode, and confirm the binary
   environment reports Python 3.10.
7. Compare the Demo predictions and row-level skip statuses with the last accepted
   output before merging the branch.

## Optional runtime checks

```bash
python3 -c 'import sys; print("Colab launcher:", sys.version)'

/content/.clean_runtime/clean_env/bin/python -c \
  'import sys,torch; assert sys.version_info[:2] == (3,12); print(sys.version, torch.__version__)'

/content/.catrange_runtime/mechanistic-py312/bin/python -c \
  'import sys,torch,esm,transformers; assert sys.version_info[:2] == (3,12); print(sys.version, torch.__version__)'

/content/.catrange_runtime/binary-py310/bin/python -c \
  'import sys,torch,esm,transformers; assert sys.version_info[:2] == (3,10); print(sys.version, torch.__version__)'
```

Full model downloads, GPU inference, and numerical regression require an actual
Colab GPU runtime and are not covered by the repository's static validation.
