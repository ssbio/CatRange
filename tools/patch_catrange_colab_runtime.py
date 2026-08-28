#!/usr/bin/env python3
"""Patch the CatRange Colab notebook for launcher-independent Python runtimes.

The transformation is deliberately fail-closed: every expected source block must
match exactly once, and the generated embedded Python is compiled before output is
written. The script can update a notebook in place or write a separate test copy.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


RELEASE = "2026-08-28-python-runtime-stability-test-2"
PREVIOUS_RELEASE = "2026-08-28-python-runtime-stability-test"
UV_VERSION = "0.8.14"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label}; found {count}.")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(
        pattern,
        lambda _match: replacement,
        text,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label}; found {count}.")
    return updated


def requirements_block(path: Path) -> tuple[str, ...]:
    values = tuple(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if not values or any("==" not in value for value in values):
        raise RuntimeError(f"Expected exact pins in {path}.")
    return values


def shell_printf(name: str, requirements: tuple[str, ...]) -> str:
    quoted = " \\\n    ".join(f"'{item}'" for item in requirements)
    return f"printf '%s\\n' \\\n    {quoted} > \"${{{name}}}\""


def patch_embedded_clean_runner(script: str, clean_requirements: tuple[str, ...]) -> str:
    script = replace_once(
        script,
        "import csv\nimport json\n",
        "import csv\nimport hashlib\nimport json\nimport platform\n",
        "CLEAN hashlib/platform import insertion point",
    )
    script = replace_once(
        script,
        "import tempfile\nimport zipfile\n",
        "import tarfile\nimport tempfile\nimport time\nimport zipfile\n",
        "CLEAN tarfile/time import insertion point",
    )

    constants = (
        f'UV_VERSION = "{UV_VERSION}"\n'
        'DEFAULT_CLEAN_PYTHON = "3.12"\n'
        f"CLEAN_REQUIREMENTS = {clean_requirements!r}\n"
        "CLEAN_IMPORTS = (\n"
        '    "torch", "numpy", "pandas", "sklearn", "scipy",\n'
        '    "tqdm", "esm", "pysam", "easydict", "gdown",\n'
        ")\n"
    )
    script = replace_once(
        script,
        'BOOTSTRAP_ENV_VAR = "CLEAN_STANDALONE_BOOTSTRAPPED"\n',
        'BOOTSTRAP_ENV_VAR = "CLEAN_STANDALONE_BOOTSTRAPPED"\n' + constants,
        "CLEAN bootstrap constants",
    )

    script = replace_regex_once(
        script,
        r'    parser\.add_argument\(\n        "--bootstrap-python",\n.*?\n    \)\n',
        '    parser.add_argument(\n'
        '        "--clean-python",\n'
        '        default=DEFAULT_CLEAN_PYTHON,\n'
        '        help="Managed Python major.minor used for CLEAN (default: 3.12).",\n'
        '    )\n',
        "CLEAN bootstrap-python argument",
    )

    script = replace_regex_once(
        script,
        r"\n\ndef auto_select_python\(.*?\n\ndef resolve_work_dir",
        "\n\ndef resolve_work_dir",
        "legacy CLEAN interpreter selection",
    )

    helpers = r'''

def uv_environment(work_dir: Path) -> Dict[str, str]:
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = str(work_dir / "uv-cache")
    env["UV_PYTHON_INSTALL_DIR"] = str(work_dir / "uv-python")
    env["UV_MANAGED_PYTHON"] = "1"
    env["UV_LINK_MODE"] = "copy"
    return env


def ensure_uv(work_dir: Path) -> Path:
    uv_bin = work_dir / "uv-bin" / "uv"
    if uv_bin.exists():
        result = subprocess.run(
            [str(uv_bin), "--version"],
            text=True,
            capture_output=True,
        )
        if result.returncode == 0 and result.stdout.strip() == f"uv {UV_VERSION}":
            return uv_bin
        uv_bin.unlink()

    uv_bin.parent.mkdir(parents=True, exist_ok=True)
    machine = platform.machine().lower()
    targets = {
        "x86_64": "x86_64-unknown-linux-gnu",
        "amd64": "x86_64-unknown-linux-gnu",
        "aarch64": "aarch64-unknown-linux-gnu",
        "arm64": "aarch64-unknown-linux-gnu",
    }
    target = targets.get(machine)
    if target is None:
        raise RuntimeError(f"Unsupported Linux architecture for uv: {machine}")

    archive_path = work_dir / f"uv-{UV_VERSION}-{target}.tar.gz"
    download_path = archive_path.with_suffix(archive_path.suffix + ".download")
    staged_uv = uv_bin.with_suffix(".download")
    release_url = (
        f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/"
        f"uv-{target}.tar.gz"
    )
    try:
        run(
            [
                "curl",
                "-fL",
                "--retry",
                "3",
                "--retry-all-errors",
                release_url,
                "-o",
                str(download_path),
            ],
            quiet=False,
        )
        download_path.replace(archive_path)
        with tarfile.open(archive_path, "r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.isfile() and Path(member.name).name == "uv"
            ]
            if len(members) != 1:
                raise RuntimeError(
                    f"Expected one uv binary in {archive_path}; found {len(members)}."
                )
            source = archive.extractfile(members[0])
            if source is None:
                raise RuntimeError(f"Could not read uv binary from {archive_path}.")
            with source, staged_uv.open("wb") as destination:
                shutil.copyfileobj(source, destination)
        staged_uv.chmod(0o755)
        staged_uv.replace(uv_bin)
    finally:
        archive_path.unlink(missing_ok=True)
        download_path.unlink(missing_ok=True)
        staged_uv.unlink(missing_ok=True)

    result = run([str(uv_bin), "--version"], capture_output=True)
    if result.stdout.strip() != f"uv {UV_VERSION}":
        uv_bin.unlink(missing_ok=True)
        raise RuntimeError(
            f"Expected uv {UV_VERSION}, received {result.stdout.strip()!r}."
        )
    return uv_bin


def environment_fingerprint(python_spec: str) -> str:
    payload = "\n".join((UV_VERSION, python_spec, *CLEAN_REQUIREMENTS)).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_clean_env(python_bin: Path, python_spec: str) -> bool:
    if not python_bin.exists():
        return False
    try:
        expected_python = tuple(int(part) for part in python_spec.split(".")[:2])
        if len(expected_python) != 2:
            return False
    except ValueError:
        return False

    expected_versions = dict(item.split("==", 1) for item in CLEAN_REQUIREMENTS)
    validation_code = (
        "import importlib,sys\n"
        "from importlib.metadata import version\n"
        f"assert sys.version_info[:2] == {expected_python!r}, sys.version\n"
        f"expected = {expected_versions!r}\n"
        "for distribution, expected_version in expected.items():\n"
        "    actual = version(distribution)\n"
        "    assert actual == expected_version, (distribution, actual, expected_version)\n"
        f"for module in {CLEAN_IMPORTS!r}:\n"
        "    importlib.import_module(module)\n"
    )
    result = subprocess.run(
        [str(python_bin), "-c", validation_code],
        text=True,
        capture_output=True,
        timeout=180,
    )
    return result.returncode == 0


def acquire_environment_lock(lock_dir: Path, timeout_seconds: int = 900) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            lock_dir.mkdir()
            return
        except FileExistsError:
            try:
                age_seconds = time.time() - lock_dir.stat().st_mtime
            except FileNotFoundError:
                continue
            if age_seconds > timeout_seconds:
                shutil.rmtree(lock_dir, ignore_errors=True)
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for CLEAN environment lock: {lock_dir}")
            time.sleep(2)
'''
    script = replace_once(
        script,
        "\n\ndef resolve_work_dir",
        helpers + "\n\ndef resolve_work_dir",
        "CLEAN runtime helper insertion point",
    )

    ensure_clean_env = r'''def ensure_clean_env(args: argparse.Namespace, work_dir: Path) -> Path:
    env_dir = work_dir / "clean_env"
    python_bin = env_dir / "bin" / "python"
    marker_path = env_dir / ".bootstrap_complete"
    lock_dir = work_dir / ".clean_env.lock"
    fingerprint = environment_fingerprint(args.clean_python)
    requirements_path = work_dir / "clean-requirements.txt"
    requirements_text = "\n".join(CLEAN_REQUIREMENTS) + "\n"
    if not requirements_path.exists() or requirements_path.read_text() != requirements_text:
        requirements_path.write_text(requirements_text)

    if (
        marker_path.exists()
        and marker_path.read_text().strip() == fingerprint
        and validate_clean_env(python_bin, args.clean_python)
    ):
        log("[setup] Reusing the validated CLEAN environment")
        return python_bin

    acquire_environment_lock(lock_dir)
    try:
        if (
            marker_path.exists()
            and marker_path.read_text().strip() == fingerprint
            and validate_clean_env(python_bin, args.clean_python)
        ):
            log("[setup] Reusing the validated CLEAN environment")
            return python_bin

        if env_dir.exists():
            log("[setup] Removing an incomplete or stale CLEAN environment")
            shutil.rmtree(env_dir)

        uv_bin = ensure_uv(work_dir)
        uv_env = uv_environment(work_dir)
        log(f"[setup] Creating CLEAN with managed Python {args.clean_python}")
        try:
            run([str(uv_bin), "python", "install", args.clean_python], env=uv_env, quiet=False)
            run(
                [
                    str(uv_bin),
                    "venv",
                    "--managed-python",
                    "--python",
                    args.clean_python,
                    str(env_dir),
                ],
                env=uv_env,
                quiet=False,
            )
            run(
                [
                    str(uv_bin),
                    "pip",
                    "install",
                    "--python",
                    str(python_bin),
                    "-r",
                    str(requirements_path),
                ],
                env=uv_env,
                quiet=False,
            )
            if not validate_clean_env(python_bin, args.clean_python):
                raise RuntimeError("CLEAN environment validation failed after installation.")
            marker_path.write_text(fingerprint + "\n")
        except Exception:
            shutil.rmtree(env_dir, ignore_errors=True)
            raise
        return python_bin
    finally:
        shutil.rmtree(lock_dir, ignore_errors=True)
'''
    script = replace_regex_once(
        script,
        r"def ensure_clean_env\(.*?\n\ndef ensure_clean_repo",
        ensure_clean_env + "\n\ndef ensure_clean_repo",
        "legacy CLEAN venv bootstrap",
    )

    compile(script, "standalone_clean_inference.py", "exec")
    return script


def upgrade_embedded_uv_bootstrap(script: str) -> str:
    """Replace the installer-based uv bootstrap in an already-patched runner."""
    if "import platform\n" not in script:
        script = replace_once(
            script,
            "import os\n",
            "import os\nimport platform\n",
            "CLEAN platform import insertion point",
        )
    if "import tarfile\n" not in script:
        script = replace_once(
            script,
            "import tempfile\n",
            "import tarfile\nimport tempfile\n",
            "CLEAN tarfile import insertion point",
        )

    ensure_uv = r'''def ensure_uv(work_dir: Path) -> Path:
    uv_bin = work_dir / "uv-bin" / "uv"
    if uv_bin.exists():
        result = subprocess.run(
            [str(uv_bin), "--version"],
            text=True,
            capture_output=True,
        )
        if result.returncode == 0 and result.stdout.strip() == f"uv {UV_VERSION}":
            return uv_bin
        uv_bin.unlink()

    uv_bin.parent.mkdir(parents=True, exist_ok=True)
    machine = platform.machine().lower()
    targets = {
        "x86_64": "x86_64-unknown-linux-gnu",
        "amd64": "x86_64-unknown-linux-gnu",
        "aarch64": "aarch64-unknown-linux-gnu",
        "arm64": "aarch64-unknown-linux-gnu",
    }
    target = targets.get(machine)
    if target is None:
        raise RuntimeError(f"Unsupported Linux architecture for uv: {machine}")

    archive_path = work_dir / f"uv-{UV_VERSION}-{target}.tar.gz"
    download_path = archive_path.with_suffix(archive_path.suffix + ".download")
    staged_uv = uv_bin.with_suffix(".download")
    release_url = (
        f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/"
        f"uv-{target}.tar.gz"
    )
    try:
        run(
            [
                "curl",
                "-fL",
                "--retry",
                "3",
                "--retry-all-errors",
                release_url,
                "-o",
                str(download_path),
            ],
            quiet=False,
        )
        download_path.replace(archive_path)
        with tarfile.open(archive_path, "r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.isfile() and Path(member.name).name == "uv"
            ]
            if len(members) != 1:
                raise RuntimeError(
                    f"Expected one uv binary in {archive_path}; found {len(members)}."
                )
            source = archive.extractfile(members[0])
            if source is None:
                raise RuntimeError(f"Could not read uv binary from {archive_path}.")
            with source, staged_uv.open("wb") as destination:
                shutil.copyfileobj(source, destination)
        staged_uv.chmod(0o755)
        staged_uv.replace(uv_bin)
    finally:
        archive_path.unlink(missing_ok=True)
        download_path.unlink(missing_ok=True)
        staged_uv.unlink(missing_ok=True)

    result = run([str(uv_bin), "--version"], capture_output=True)
    if result.stdout.strip() != f"uv {UV_VERSION}":
        uv_bin.unlink(missing_ok=True)
        raise RuntimeError(
            f"Expected uv {UV_VERSION}, received {result.stdout.strip()!r}."
        )
    return uv_bin
'''
    script = replace_regex_once(
        script,
        r"def ensure_uv\(work_dir: Path\) -> Path:\n.*?(?=\n\ndef environment_fingerprint)",
        ensure_uv,
        "installer-based CLEAN uv bootstrap",
    )
    compile(script, "standalone_clean_inference.py", "exec")
    return script


def upgrade_pipeline_uv_bootstrap(text: str) -> str:
    prefix = "standalone_clean_script.write_text("
    start = text.index(prefix) + len(prefix)
    end_marker = ")\nstandalone_clean_script.chmod(0o755)"
    end = text.index(end_marker, start)
    embedded_script = ast.literal_eval(text[start:end])
    embedded_script = upgrade_embedded_uv_bootstrap(embedded_script)
    return text[:start] + repr(embedded_script) + text[end:]


def patch_pipeline_cell(
    text: str,
    clean_requirements: tuple[str, ...],
    mechanistic_requirements: tuple[str, ...],
    binary_requirements: tuple[str, ...],
) -> str:
    prefix = "standalone_clean_script.write_text("
    start = text.index(prefix) + len(prefix)
    end_marker = ")\nstandalone_clean_script.chmod(0o755)"
    end = text.index(end_marker, start)
    embedded_literal = text[start:end]
    embedded_script = ast.literal_eval(embedded_literal)
    embedded_script = patch_embedded_clean_runner(embedded_script, clean_requirements)
    text = text[:start] + repr(embedded_script) + text[end:]

    old_apt = '''apt_cmd = (
    "apt-get update -qq && "
    "DEBIAN_FRONTEND=noninteractive apt-get install -y "
    "python3.10-venv python3.11-venv python3.12-venv python3-venv python3-full"
)
print("[CLEAN] Preparing the CLEAN runtime...")
subprocess.run(
    ["bash", "-lc", apt_cmd],
    check=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
'''
    new_apt = '''apt_cmd = (
    "apt-get update -qq && "
    "DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
    "git curl ca-certificates unzip"
)
print("[CLEAN] Preparing the CLEAN runtime...")
subprocess.run(["bash", "-lc", apt_cmd], check=True)
'''
    text = replace_once(text, old_apt, new_apt, "generic Colab prerequisite install")

    text = replace_once(
        text,
        '''    "--bootstrap-python",
    sys.executable,
''',
        '''    "--clean-python",
    "3.12",
''',
        "unsafe CLEAN launcher interpreter argument",
    )

    text = replace_once(
        text,
        '''    "CLEAN_WORK_DIR": str(clean_work_dir),
''',
        '''    "CLEAN_WORK_DIR": str(clean_work_dir),
    "CLEAN_PYTHON": str(clean_work_dir / "clean_env" / "bin" / "python"),
    "UV_BIN": str(clean_work_dir / "uv-bin" / "uv"),
''',
        "CLEAN runtime environment exports",
    )

    old_mechanistic = r'''  echo "[setup] Installing system deps for Python 3.12…"
  sudo sed -i 's/^[[:space:]]*deb-src .*r2u\.stat\.illinois\.edu.*$/# &/' /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null || true
  sudo apt-get update -qq > /dev/null
  sudo apt-get install -qq -y python3.12 python3.12-venv python3-distutils curl wget unzip > /dev/null
  curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  python3.12 /tmp/get-pip.py --quiet
  echo "[setup] Installing Python deps…"
  python3.12 -m pip install -q \\
    numpy==2.1 pandas==2.2.2 scikit-learn==1.7.1 imbalanced-learn==0.8.1 \\
    seaborn==0.11.2 joblib==1.2.0 ipython==7.34.0 \\
    matplotlib==3.10.5 \\
    notebook==6.5.4 jupyterlab==3.6.1 openpyxl==3.1.2 xlrd==2.0.1 XlsxWriter==3.0.3 > /tmp/catrange_pydeps_base.log 2>&1 || { cat /tmp/catrange_pydeps_base.log; exit 1; }
  python3.12 -m pip install -q \\
    xgboost==2.1.4 torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0 \\
    tqdm esm==3.2.3 httpx==0.28.1 biotite==1.2.0 \\
    # huggingface_hub==1.2.3 #transformers==4.46.3
    huggingface_hub==0.25.2 > /tmp/catrange_pydeps_models.log 2>&1 || { cat /tmp/catrange_pydeps_models.log; exit 1; }
  : > latex_queue.txt
  echo "[run] Starting mechanistic inference… MODE=${MODE}  CSV_PATH=${CSV_PATH}  BATCH_SIZE=${BATCH_SIZE}  ENCODER=${ENCODER:-esmc}  ALLOW_ENCODER_MISMATCH=${ALLOW_ENCODER_MISMATCH:-1}"
  if ! MODE="$MODE" CSV_PATH="$CSV_PATH" BATCH_SIZE="$BATCH_SIZE" stdbuf -oL python3.12 - <<'PY' 2>/tmp/catrange_mechanistic_stderr.log
'''
    mech_printf = shell_printf("MECH_REQUIREMENTS", mechanistic_requirements)
    new_mechanistic = f'''  echo "[setup] Preparing managed Python 3.12 for mechanistic inference…"
  : "${{UV_BIN:?CLEAN bootstrap did not provide UV_BIN}}"
  CATRANGE_RUNTIME_DIR="${{RUNTIME_ROOT}}/.catrange_runtime"
  MECH_ENV="${{CATRANGE_RUNTIME_DIR}}/mechanistic-py312"
  MECH_PY="${{MECH_ENV}}/bin/python"
  MECH_REQUIREMENTS="${{CATRANGE_RUNTIME_DIR}}/mechanistic-py312-requirements.txt"
  MECH_MARKER="${{MECH_ENV}}/.bootstrap_complete"
  mkdir -p "${{CATRANGE_RUNTIME_DIR}}"
  {mech_printf}
  MECH_FINGERPRINT="py312-uv{UV_VERSION}-$(sha256sum "${{MECH_REQUIREMENTS}}" | cut -d' ' -f1)"
  export UV_CACHE_DIR="${{CATRANGE_RUNTIME_DIR}}/uv-cache"
  export UV_PYTHON_INSTALL_DIR="${{CLEAN_WORK_DIR}}/uv-python"
  export UV_MANAGED_PYTHON=1
  export UV_LINK_MODE=copy
  MECH_VALID=0
  if [ -x "${{MECH_PY}}" ] && [ -f "${{MECH_MARKER}}" ] && [ "$(tr -d '\\r\\n' < "${{MECH_MARKER}}")" = "${{MECH_FINGERPRINT}}" ]; then
    if "${{MECH_PY}}" -c 'import sys,torch,numpy,pandas,sklearn,joblib,xgboost,tqdm,esm,httpx,biotite,transformers,huggingface_hub; assert sys.version_info[:2] == (3, 12)' >/dev/null 2>&1; then
      MECH_VALID=1
    fi
  fi
  if [ "${{MECH_VALID}}" = "1" ]; then
    echo "[setup] Reusing the validated mechanistic environment"
  else
    rm -rf "${{MECH_ENV}}"
    "${{UV_BIN}}" python install 3.12
    "${{UV_BIN}}" venv --managed-python --python 3.12 "${{MECH_ENV}}"
    "${{UV_BIN}}" pip install --python "${{MECH_PY}}" -r "${{MECH_REQUIREMENTS}}"
    "${{MECH_PY}}" -c 'import sys,torch,numpy,pandas,sklearn,joblib,xgboost,tqdm,esm,httpx,biotite,transformers,huggingface_hub; assert sys.version_info[:2] == (3, 12)'
    printf '%s\\n' "${{MECH_FINGERPRINT}}" > "${{MECH_MARKER}}"
  fi
  : > latex_queue.txt
  echo "[run] Starting mechanistic inference… MODE=${{MODE}}  CSV_PATH=${{CSV_PATH}}  BATCH_SIZE=${{BATCH_SIZE}}  ENCODER=${{ENCODER:-esmc}}  ALLOW_ENCODER_MISMATCH=${{ALLOW_ENCODER_MISMATCH:-1}}"
  if ! MODE="$MODE" CSV_PATH="$CSV_PATH" BATCH_SIZE="$BATCH_SIZE" stdbuf -oL "${{MECH_PY}}" - <<'PY' 2>/tmp/catrange_mechanistic_stderr.log
'''
    text = replace_regex_once(
        text,
        r'  echo "\[setup\] Installing system deps for Python 3\.12…"\n.*?'
        r'  if ! MODE="\$MODE" CSV_PATH="\$CSV_PATH" BATCH_SIZE="\$BATCH_SIZE" '
        r"stdbuf -oL python3\.12 - <<'PY' 2>/tmp/catrange_mechanistic_stderr\.log\n",
        new_mechanistic,
        "mechanistic Python bootstrap",
    )

    old_binary = r'''  echo "[setup] Installing system deps for Python 3.10 …"
  echo "Trying to: Install dependencies, download and unzip model weights, get dependencies  [~2 minute]"
  sudo sed -i 's/^[[:space:]]*deb-src .*r2u\.stat\.illinois\.edu.*$/# &/' /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null || true
  sudo apt-get update -qq > /dev/null
  sudo apt-get install -qq -y python3.10 python3.10-distutils python3.10-venv curl wget unzip > /dev/null
  curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  python3.10 /tmp/get-pip.py --quiet
  python3.10 -m pip install -q numpy==1.23.5 pandas==1.5.3 scikit-learn==1.1.3 imbalanced-learn==0.8.1 matplotlib==3.6.3 seaborn==0.11.2 joblib==1.2.0 ipython==7.33.0 notebook==6.5.4 jupyterlab==3.6.1 openpyxl==3.1.2 xlrd==2.0.1 XlsxWriter==3.0.3 > /tmp/catrange_binary_base.log 2>&1 || { cat /tmp/catrange_binary_base.log; exit 1; }
  python3.10 -m pip install -q xgboost==2.1.4 torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0 transformers==4.33.3 fair-esm==2.0.0 mkl==2022.1.0 mkl-service==2.4.0 intel-openmp==2022.1.0 tqdm > /tmp/catrange_binary_models.log 2>&1 || { cat /tmp/catrange_binary_models.log; exit 1; }
    : > latex_queue.txt
    if ! MODE="$MODE" CSV_PATH="$CSV_PATH" BATCH_SIZE="$BATCH_SIZE" stdbuf -oL python3.10 - <<'PY' 2>/tmp/catrange_binary_stderr.log
'''
    binary_printf = shell_printf("BINARY_REQUIREMENTS", binary_requirements)
    new_binary = f'''  echo "[setup] Preparing managed Python 3.10 for binary inference…"
  : "${{UV_BIN:?CLEAN bootstrap did not provide UV_BIN}}"
  CATRANGE_RUNTIME_DIR="${{RUNTIME_ROOT}}/.catrange_runtime"
  BINARY_ENV="${{CATRANGE_RUNTIME_DIR}}/binary-py310"
  BINARY_PY="${{BINARY_ENV}}/bin/python"
  BINARY_REQUIREMENTS="${{CATRANGE_RUNTIME_DIR}}/binary-py310-requirements.txt"
  BINARY_MARKER="${{BINARY_ENV}}/.bootstrap_complete"
  mkdir -p "${{CATRANGE_RUNTIME_DIR}}"
  {binary_printf}
  BINARY_FINGERPRINT="py310-uv{UV_VERSION}-$(sha256sum "${{BINARY_REQUIREMENTS}}" | cut -d' ' -f1)"
  export UV_CACHE_DIR="${{CATRANGE_RUNTIME_DIR}}/uv-cache"
  export UV_PYTHON_INSTALL_DIR="${{CLEAN_WORK_DIR}}/uv-python"
  export UV_MANAGED_PYTHON=1
  export UV_LINK_MODE=copy
  BINARY_VALID=0
  if [ -x "${{BINARY_PY}}" ] && [ -f "${{BINARY_MARKER}}" ] && [ "$(tr -d '\\r\\n' < "${{BINARY_MARKER}}")" = "${{BINARY_FINGERPRINT}}" ]; then
    if "${{BINARY_PY}}" -c 'import sys,torch,numpy,pandas,sklearn,imblearn,joblib,xgboost,transformers,esm,tqdm; assert sys.version_info[:2] == (3, 10)' >/dev/null 2>&1; then
      BINARY_VALID=1
    fi
  fi
  if [ "${{BINARY_VALID}}" = "1" ]; then
    echo "[setup] Reusing the validated binary environment"
  else
    rm -rf "${{BINARY_ENV}}"
    "${{UV_BIN}}" python install 3.10
    "${{UV_BIN}}" venv --managed-python --python 3.10 "${{BINARY_ENV}}"
    "${{UV_BIN}}" pip install --python "${{BINARY_PY}}" -r "${{BINARY_REQUIREMENTS}}"
    "${{BINARY_PY}}" -c 'import sys,torch,numpy,pandas,sklearn,imblearn,joblib,xgboost,transformers,esm,tqdm; assert sys.version_info[:2] == (3, 10)'
    printf '%s\\n' "${{BINARY_FINGERPRINT}}" > "${{BINARY_MARKER}}"
  fi
  : > latex_queue.txt
  if ! MODE="$MODE" CSV_PATH="$CSV_PATH" BATCH_SIZE="$BATCH_SIZE" stdbuf -oL "${{BINARY_PY}}" - <<'PY' 2>/tmp/catrange_binary_stderr.log
'''
    text = replace_regex_once(
        text,
        r'  echo "\[setup\] Installing system deps for Python 3\.10 …"\n.*?'
        r'    if ! MODE="\$MODE" CSV_PATH="\$CSV_PATH" BATCH_SIZE="\$BATCH_SIZE" '
        r"stdbuf -oL python3\.10 - <<'PY' 2>/tmp/catrange_binary_stderr\.log\n",
        new_binary,
        "binary Python bootstrap",
    )

    legacy_merge = '''if [ -n "${CLEAN_SCREENED_CSV:-}" ] && [ -f "${CLEAN_SCREENED_CSV}" ] && [ -n "${CLEAN_STANDALONE_SCRIPT:-}" ] && [ -f "${CLEAN_STANDALONE_SCRIPT}" ]; then
  echo "[CLEAN] Merging EC annotations back into inference_results.csv..."
  python3 "${CLEAN_STANDALONE_SCRIPT}"     --work-dir "${CLEAN_WORK_DIR:-./.clean_runtime}"     merge     --screened-csv "${CLEAN_SCREENED_CSV}"     --catrange-output-csv "inference_results.csv"     --output-csv "${CLEAN_MERGED_OUTPUT_CSV:-final_inference_results.csv}"
  mv "${CLEAN_MERGED_OUTPUT_CSV:-final_inference_results.csv}" "inference_results.csv"
fi

'''
    text = replace_once(text, legacy_merge, "", "binary-only CLEAN merge")

    fixed_merge = '''if [ -n "${CLEAN_SCREENED_CSV:-}" ] && [ -f "${CLEAN_SCREENED_CSV}" ] && [ -n "${CLEAN_STANDALONE_SCRIPT:-}" ] && [ -f "${CLEAN_STANDALONE_SCRIPT}" ]; then
  echo "[CLEAN] Merging EC annotations back into inference_results.csv..."
  CLEAN_STANDALONE_BOOTSTRAPPED=1 "${CLEAN_PYTHON}" "${CLEAN_STANDALONE_SCRIPT}" \\
    --work-dir "${CLEAN_WORK_DIR:-./.clean_runtime}" \\
    merge \\
    --screened-csv "${CLEAN_SCREENED_CSV}" \\
    --catrange-output-csv "inference_results.csv" \\
    --output-csv "${CLEAN_MERGED_OUTPUT_CSV:-final_inference_results.csv}"
  mv "${CLEAN_MERGED_OUTPUT_CSV:-final_inference_results.csv}" "inference_results.csv"
fi
'''
    summary_marker = "\nfi\n\npython3 - <<'PY'\nfrom pathlib import Path\n\nimport math\n"
    text = replace_once(
        text,
        summary_marker,
        "\nfi\n\n" + fixed_merge + "\npython3 - <<'PY'\nfrom pathlib import Path\n\nimport math\n",
        "post-branch summary insertion point",
    )

    forbidden = (
        "--bootstrap-python",
        "get-pip.py",
        "python3.12 -m pip",
        "python3.10 -m pip",
        "python3.12-venv",
        "python3.10-venv",
    )
    for fragment in forbidden:
        if fragment in text:
            raise RuntimeError(f"Legacy runtime fragment remained after patch: {fragment}")
    return text


def patch_notebook(source_path: Path, destination_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    clean_requirements = requirements_block(root / "envs" / "colab-clean-py312.txt")
    mechanistic_requirements = requirements_block(
        root / "envs" / "colab-catrange-mechanistic-py312.txt"
    )
    binary_requirements = requirements_block(root / "envs" / "colab-catrange-binary-py310.txt")

    notebook = json.loads(source_path.read_text(encoding="utf-8"))
    patched_pipeline = False
    for cell in notebook.get("cells", []):
        source = "".join(cell.get("source", []))
        source = source.replace("2026-03-17-optimized", RELEASE)
        source = source.replace(PREVIOUS_RELEASE, RELEASE)
        if "#@title 2. Run CLEAN + CatRange Inference pipeline" in source:
            if "UV_UNMANAGED_INSTALL" in source:
                source = upgrade_pipeline_uv_bootstrap(source)
            elif f"uv/releases/download/{{UV_VERSION}}" not in source:
                source = patch_pipeline_cell(
                    source,
                    clean_requirements,
                    mechanistic_requirements,
                    binary_requirements,
                )
            patched_pipeline = True
        cell["source"] = source.splitlines(keepends=True)
        if cell.get("cell_type") == "code":
            cell["execution_count"] = None
            cell["outputs"] = []

    if not patched_pipeline:
        raise RuntimeError("Could not find the CatRange pipeline cell.")

    destination_path.write_text(
        json.dumps(notebook, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", nargs="?", type=Path)
    args = parser.parse_args()
    destination = args.destination or args.source
    patch_notebook(args.source.resolve(), destination.resolve())
    print(f"Patched notebook: {destination.resolve()}")


if __name__ == "__main__":
    main()
