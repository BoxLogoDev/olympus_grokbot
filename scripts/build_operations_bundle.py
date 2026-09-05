"""Build a code/Skill-only zip from a clean tracked checkout; never include private state."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ("runtime/", "skills/", "templates/", "spec/", "scripts/", "tests/", "playbooks/", "registry/", "prompts/", "characters/", "examples/", "docs/")
EXACT = {"requirements-dev.txt", "README.md", "spec/operations-v1.yaml", "spec/olympus-contracts-v1.yaml",
         "registry/slots.yaml", "OLYMPUS_Agent_Architecture_v1.3.md"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): parser.error("output already exists")
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if dirty.strip(): parser.error("commit/review changes first; clean tracked checkout required")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    names = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    names = [n for n in names if n in EXACT or n.startswith(PREFIXES) or (n.startswith("OLYMPUS") and n.endswith(".md"))]
    forbidden = (".sqlite", ".db", ".env", ".pem", ".key")
    if any(n.endswith(forbidden) or "private" in Path(n).parts for n in names):
        parser.error("private state in bundle allowlist")
    contents = {n: (ROOT / n).read_bytes() for n in names}
    manifest = {"implementation_commit": commit, "policy_version": "1.3",
                "policy_commit": "30363791228181b986cc94491ab938ee544699f4",
                "mode": "OPERATIONS_EVIDENCE", "runtime_verified": False,
                "files": {n: hashlib.sha256(raw).hexdigest() for n, raw in contents.items()}}
    with zipfile.ZipFile(args.output, "x", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in contents.items(): archive.writestr(name, raw)
        archive.writestr("BUNDLE-MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({"path": str(args.output.resolve()), "commit": commit,
                      "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__ == "__main__": main()
