#!/usr/bin/env python3
"""Check research-release boundaries, size limits and common credential patterns.

Default: inspect tracked and nonignored worktree files and HEAD ancestry.
--git-ref COMMIT: inspect exactly the proposed commit and its ancestry.
This is a publication guard, not proof that arbitrary data contains no secrets.
Diagnostics identify files and rules, never matched credential values.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


ROOTS = {
    ".github", ".gitignore", ".gitattributes", "README.md", "CatRange_Inference_Interface.ipynb",
    "ablation", "benchmarks", "catrange_model", "data", "envs", "inference",
    "results", "scripts", "tools",
    "LICENSE", "NOTICE", "LICENSES",
}
BACKEND = ("webapp/", "deploy/", "deployment/", "secrets/", "operations/")
TOKEN_RULES = {
    "private-key": rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "github-token": rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b",
    "huggingface-token": rb"\bhf_[A-Za-z0-9]{30,}\b",
    "aws-access-key": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "slack-token": rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b",
    "sendgrid-token": rb"\bSG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{30,}\b",
    "credential-in-url": rb"https?://[^\s/:@]+:[^\s/@]{8,}@",
}
SERVICE_IMPORT = re.compile(
    rb"(?m)^\s*(?:from\s+(?:fastapi|smtplib|kubernetes|webapp)(?:[.\s])|import\s+(?:smtplib|kubernetes|webapp)\b)"
)


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def forbidden_path(name: str, history: bool = False) -> str | None:
    path = Path(name)
    if name.startswith(BACKEND) or name.startswith(".github/workflows/build-webapp"):
        return "backend-path"
    if path.name in {".env", "id_rsa", "id_ed25519", "smtp-password", "hostinger-mail-api-key"}:
        return "credential-path"
    if path.suffix.lower() in {".pem", ".key", ".sqlite", ".sqlite3", ".db"}:
        return "credential-or-runtime-file"
    if not history and path.parts[0] not in ROOTS:
        return "unreviewed-top-level-path"
    return None


def content_rules(name: str, data: bytes) -> list[str]:
    findings = [rule for rule, pattern in TOKEN_RULES.items() if re.search(pattern, data)]
    if name.endswith(".py") and SERVICE_IMPORT.search(data):
        findings.append("service-import")
    return findings


def inspect(ref: str | None) -> tuple[int, list[tuple[str, str]]]:
    issues: list[tuple[str, str]] = []
    if ref:
        names = git("ls-tree", "-r", "--name-only", "-z", ref).decode().rstrip("\0").split("\0")
    else:
        names = sorted(set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().rstrip("\0").split("\0")))
    for name in filter(None, names):
        reason = forbidden_path(name)
        if reason:
            issues.append((name, reason))
            continue
        if ref:
            entry = git("ls-tree", ref, "--", name).decode()
            if not entry.startswith(("100644 ", "100755 ")):
                issues.append((name, "non-regular-file"))
                continue
            data = git("show", f"{ref}:{name}")
        else:
            path = Path(name)
            if path.is_symlink() or not path.is_file():
                issues.append((name, "non-regular-or-missing-file"))
                continue
            data = path.read_bytes()
        if len(data) >= 100 * 1024**2:
            issues.append((name, "GitHub-100-MiB-limit"))
        issues.extend((name, rule) for rule in content_rules(name, data))
    # A clean tip alone cannot exclude service code in earlier commits.
    for line in git("rev-list", "--objects", ref or "HEAD").decode().splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and (reason := forbidden_path(parts[1], history=True)):
            issues.append((parts[1], "history-" + reason))
    return len(names), sorted(set(issues))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-ref")
    args = parser.parse_args()
    if args.git_ref:
        args.git_ref = git("rev-parse", "--verify", args.git_ref + "^{commit}").decode().strip()
    count, issues = inspect(args.git_ref)
    for name, reason in issues:
        print(f"FAIL {reason}: {name}")
    print(f"Public release: {count} files checked; {len(issues)} findings")
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
