"""Check accidental service publication, including deleted historical files."""
import importlib.util
import os
from pathlib import Path
import subprocess


SPEC = importlib.util.spec_from_file_location(
    "check_public_release", Path(__file__).resolve().parents[1] / "check_public_release.py"
)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def test_service_and_credentials_are_rejected():
    assert CHECK.forbidden_path("webapp/api/app/main.py") == "backend-path"
    assert CHECK.forbidden_path(".env") == "credential-path"
    assert CHECK.forbidden_path("data/raw/experiment.csv") is None
    assert CHECK.content_rules("driver.py", b"from fastapi import FastAPI\n") == ["service-import"]
    token = b"ghp_" + b"X" * 36
    assert CHECK.content_rules("config.txt", token) == ["github-token"]


def test_deleted_backend_is_still_rejected_from_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = dict(os.environ, GIT_AUTHOR_NAME="Release test", GIT_AUTHOR_EMAIL="test@example.invalid",
               GIT_COMMITTER_NAME="Release test", GIT_COMMITTER_EMAIL="test@example.invalid")

    def git(*args):
        return subprocess.check_output(["git", *args], env=env, stderr=subprocess.DEVNULL)

    git("init", "-q")
    Path("README.md").write_text("Research\n")
    Path("webapp").mkdir()
    Path("webapp/server.py").write_text("print('server')\n")
    git("add", ".")
    git("commit", "-qm", "Initial")
    Path("webapp/server.py").unlink()
    git("add", "-u")
    git("commit", "-qm", "Remove server")
    _, issues = CHECK.inspect("HEAD")
    assert ("webapp/server.py", "history-backend-path") in issues
