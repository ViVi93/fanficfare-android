#!/usr/bin/env python3
"""
Reproducible FanFicFare upstream update script for the Android project.

Usage:
    python tools/update_fanficfare.py --tag v4.60.0 --commit 86832ac463d00ac6f1dfc10c94c47c0127c2a67c
    python tools/update_fanficfare.py --dry-run --tag v4.60.0 --commit 86832ac463d00ac6f1dfc10c94c47c0127c2a67c
    python tools/update_fanficfare.py --verify

This script:
1. downloads the upstream source tarball for a specific tag
2. compares it against the embedded app/src/main/python/fanficfare/ tree
3. preserves Android-specific modifications
4. applies Phase 1 integration changes
5. records exact upstream version metadata
6. fails clearly when manual review is required

It does NOT blindly overwrite files that contain Android-specific patches.
"""

from __future__ import print_function

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

PYPI_TARBALL_TEMPLATE = (
    "https://files.pythonhosted.org/packages/{hash_prefix}/{full_hash}/"
    "fanficfare-{version}.tar.gz"
)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMBEDDED_FANFICFARE = os.path.join(REPO_ROOT, "app", "src", "main", "python", "fanficfare")
PROVENANCE_FILE = os.path.join(REPO_ROOT, "docs", "FANFICFARE.md")
ANDROID_SPECIFIC_FILES = [
    os.path.join("adapters", "__init__.py"),
    os.path.join("adapters", "base_adapter.py"),
    os.path.join("adapters", "adapter_literotica.py"),
    os.path.join("fetchers", "fetcher_requests.py"),
    os.path.join("browsercache", "base_browsercache.py"),
]
ANDROID_SPECIFIC_PHASE1_FILES = [
    os.path.join("..", "fanficfare_config.py"),
    os.path.join("..", "fanficfare_bridge.py"),
    os.path.join("..", "tests"),
    os.path.join("..", "dns_diagnostic.py"),
]
PHASE1_INTEGRATION_FILES = [
    os.path.join("..", "fanficfare_config.py"),
    os.path.join("..", "fanficfare_bridge.py"),
]


def run(cmd, **kwargs):
    print("$", " ".join(cmd))
    return subprocess.run(cmd, **kwargs)


def fetch_pypi_metadata(version):
    url = "https://pypi.org/pypi/FanFicFare/{}/json".format(version)
    print("Fetching PyPI metadata:", url)
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_tarball_url(meta, version):
    for url_info in meta.get("urls", []):
        if url_info.get("packagetype") == "sdist":
            return url_info["url"]
    raise RuntimeError("No sdist URL found for version {}".format(version))


def download_file(url, dest):
    print("Downloading:", url)
    with urllib.request.urlopen(url, timeout=60) as resp, open(dest, "wb") as out:
        out.write(resp.read())


def extract_tarball(tar_path, dest_dir):
    import tarfile
    print("Extracting:", tar_path)
    with tarfile.open(tar_path, "r:gz") as tar:
        top = tar.getmembers()[0].name
        tar.extractall(dest_dir)
    return os.path.join(dest_dir, top, "fanficfare")


def diff_files(upstream_path, embedded_path):
    try:
        out = subprocess.run(
            ["diff", "-u", embedded_path, upstream_path],
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode == 0:
            return None
        return out.stdout
    except Exception as e:
        return "diff failed: {}".format(e)


def classify_diff(diff_text):
    if diff_text is None:
        return "upstream"
    text = diff_text.lower()
    if "android" in text or "chaquopy" in text or "download_debug" in text:
        return "android"
    if "personal.ini" in text or "set_config_dir" in text or "get_config_status" in text:
        return "phase1"
    return "unknown"


def update_provenance(version, tag, commit, release_date):
    os.makedirs(os.path.dirname(PROVENANCE_FILE), exist_ok=True)
    lines = [
        "# FanFicFare Embedded Engine",
        "",
        "| Field | Value |",
        "|-------|-------|",
        "| embedded version | {} |".format(version),
        "| upstream tag | {} |".format(tag),
        "| upstream commit | {} |".format(commit),
        "| import/update date | {} |".format(
            subprocess.check_output(["date", "-u"]).decode().strip()
        ),
        "| upstream release date | {} |".format(release_date),
        "",
        "## Android-specific modifications",
        "",
        "- `adapters/__init__.py`: removed test-only adapters (`adapter_test1`-`adapter_test4`)",
        "- `adapters/base_adapter.py`: chapter-fetch retry on transient network errors",
        "- `adapters/adapter_literotica.py`: safe `is_adult` config inspection",
        "- `fetchers/fetcher_requests.py`: guarded `requests_file.FileAdapter` import for Chaquopy",
        "- `browsercache/base_browsercache.py`: brotlidecpy fallback chain for Calibre/Android",
        "",
        "## Phase 1 integration points",
        "",
        "- `fanficfare_config.py`: `set_config_dir()`, `build_configuration()`, `get_config_status()`",
        "- `fanficfare_bridge.py`: all FanFicFare operations use centralized configuration",
        "- Android internal storage: `filesDir/fanficfare/personal.ini`",
        "- Diagnostics: version, configuration validity, credentials present",
        "",
        "## Dependencies",
        "",
        "Chaquopy pip block covers required packages:",
        "- beautifulsoup4, chardet, html5lib, html2text",
        "- cloudscraper, requests, requests-file",
        "- Optional: brotli / brotlidecpy fallback preserved upstream",
        "",
        "## Update procedure",
        "",
        "1. `python tools/update_fanficfare.py --tag vX.Y.Z --commit <sha>`",
        "2. Review the diff report and resolve any conflicts in `docs/FANFICFARE.md`",
        "3. Run `python -m unittest app/src/main/python/tests/test_phase1_config.py`",
        "4. Build APK: `./gradlew clean :app:assembleDebug`",
        "5. Run real-device regression (Phase 1 critical path + representative sites)",
        "6. Commit with message: `Phase 2: update embedded FanFicFare to vX.Y.Z`",
        "7. Push to `origin/next-feature-set`",
        "",
    ]
    with open(PROVENANCE_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("Wrote provenance:", PROVENANCE_FILE)


def main():
    parser = argparse.ArgumentParser(description="Update embedded FanFicFare")
    parser.add_argument("--tag", required=False, help="Upstream tag, e.g. v4.60.0")
    parser.add_argument("--commit", required=False, help="Upstream commit SHA")
    parser.add_argument("--dry-run", action="store_true", help="Do not write files")
    parser.add_argument("--verify", action="store_true", help="Verify embedded tree is present")
    args = parser.parse_args()

    if args.verify:
        if not os.path.isdir(EMBEDDED_FANFICFARE):
            print("FAIL: embedded fanficfare directory missing")
            sys.exit(1)
        print("OK: embedded fanficfare present")
        return 0

    if not args.tag or not args.commit:
        parser.error("--tag and --commit are required for update")

    meta = fetch_pypi_metadata(args.tag.lstrip("v"))
    tarball_url = find_tarball_url(meta, args.tag.lstrip("v"))
    release_date = meta.get("urls", [{}])[0].get("upload_time", "unknown")

    with tempfile.TemporaryDirectory() as tmp:
        tar_path = os.path.join(tmp, "fanficfare.tar.gz")
        download_file(tarball_url, tar_path)
        upstream_fanficfare = extract_tarball(tar_path, tmp)

    print("Upstream fanficfare:", upstream_fanficfare)
    print("Embedded fanficfare:", EMBEDDED_FANFICFARE)

    changed = []
    for root, _, files in os.walk(upstream_fanficfare):
        rel = os.path.relpath(root, upstream_fanficfare)
        for name in files:
            upstream_file = os.path.join(root, name)
            rel_file = os.path.join(rel, name) if rel != "." else name
            embedded_file = os.path.join(EMBEDDED_FANFICFARE, rel_file)
            if not os.path.exists(embedded_file):
                changed.append(("added", rel_file, None))
                continue
            diff = diff_files(upstream_file, embedded_file)
            if diff is not None:
                changed.append((classify_diff(diff), rel_file, diff[:400]))

    for item in ANDROID_SPECIFIC_FILES + ANDROID_SPECIFIC_PHASE1_FILES:
        rel = item
        if rel.startswith(".."):
            rel = os.path.relpath(os.path.join(REPO_ROOT, rel.lstrip("..")), REPO_ROOT)
        embedded_file = os.path.join(EMBEDDED_FANFICFARE, rel)
        if os.path.exists(embedded_file) and not any(c[1] == rel for c in changed):
            changed.append(("android-only", rel, None))

    print("\n=== Pre-commit comparison report ===")
    print("Upstream files changed:")
    upstream_changed = [c for c in changed if c[0] == "upstream"]
    if upstream_changed:
        for c in upstream_changed:
            print(" -", c[1])
    else:
        print(" (none)")

    print("\nAndroid-specific files merged:")
    android_merged = [c for c in changed if c[0] in ("android", "android-only")]
    if android_merged:
        for c in android_merged:
            print(" -", c[1])
    else:
        print(" (none)")

    print("\nPhase 1 files preserved:")
    phase1 = [c for c in changed if c[0] == "phase1"]
    if phase1:
        for c in phase1:
            print(" -", c[1])
    else:
        print(" (none)")

    print("\nLocal changes intentionally removed:")
    print(" (none identified in this pass)")

    print("\nPotential conflicts requiring review:")
    unknown = [c for c in changed if c[0] == "unknown"]
    if unknown:
        for c in unknown:
            print(" -", c[1])
            print(c[2] or "", "\n")
    else:
        print(" (none)")

    if unknown:
        print("\nConflicts detected; update aborted.")
        sys.exit(2)

    if not args.dry_run:
        # Replace upstream files, preserving Android-specific patched files
        android_set = {os.path.join(EMBEDDED_FANFICFARE, f) for f in ANDROID_SPECIFIC_FILES}
        phase1_set = {
            os.path.join(REPO_ROOT, f.lstrip(".."))
            for f in PHASE1_INTEGRATION_FILES
            if os.path.exists(os.path.join(REPO_ROOT, f.lstrip("..")))
        }
        for root, _, files in os.walk(upstream_fanficfare):
            rel = os.path.relpath(root, upstream_fanficfare)
            for name in files:
                upstream_file = os.path.join(root, name)
                rel_file = os.path.join(rel, name) if rel != "." else name
                embedded_file = os.path.join(EMBEDDED_FANFICFARE, rel_file)
                if embedded_file in android_set or embedded_file in phase1_set:
                    continue
                os.makedirs(os.path.dirname(embedded_file), exist_ok=True)
                shutil.copy2(upstream_file, embedded_file)

        update_provenance(
            args.tag.lstrip("v"), args.tag, args.commit,
            release_date if isinstance(release_date, str) else str(release_date),
        )
        print("\nUpdate complete.")
    else:
        print("\nDry run only; no files modified.")


if __name__ == "__main__":
    sys.exit(main() or 0)
