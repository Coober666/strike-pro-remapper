#!/usr/bin/env python3
"""Versioned, verified Git/worktree backup. No checkout, sync, deletion or overwrite."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=dict(os.environ, GIT_OPTIONAL_LOCKS="0")).stdout


def digest(path):
    with path.open("rb") as stream:
        result = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def source_state(root):
    names = sorted(set(os.fsdecode(p) for p in git(
        root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0") if p))
    result = {}
    for name in names:
        path = root / name
        # Do not follow a tracked directory symlink to read an external file.
        if any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents):
            raise ValueError("A source path has a linked parent")
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue  # Deleted tracked files are retained in the Git patches.
        if stat.S_ISLNK(info.st_mode):
            value = {"link": os.readlink(path)}
        elif stat.S_ISREG(info.st_mode):
            value = {"sha256": digest(path), "bytes": info.st_size}
        else:
            raise ValueError("Submodules and special files need a separate backup")
        result[name] = dict(value, mode=stat.S_IMODE(info.st_mode))
    return result


def worktree_state(root):
    return {
        "head": git(root, "rev-parse", "HEAD").decode().strip(),
        "index_patch": git(root, "diff", "--cached", "--binary", "--no-ext-diff"),
        "working_patch": git(root, "diff", "--binary", "--no-ext-diff"),
        "status": git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all"),
        "files": source_state(root),
    }


def worktrees(repo):
    records = git(repo, "worktree", "list", "--porcelain", "-z").split(b"\0\0")
    return [Path(os.fsdecode(record.split(b"\0")[0][9:])) for record in records
            if record.startswith(b"worktree ")]


def check_destination(destination, mount):
    for path in [destination, *destination.parents]:
        if path.is_symlink():
            raise ValueError("Backup destinations cannot contain symlinks")
    if mount is not None:
        if not mount.is_mount() or not destination.resolve().is_relative_to(mount.resolve()):
            raise ValueError("Required NAS mount is absent or does not contain the destination")


def verify_backup(folder):
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest.get("status") != "complete" or (folder / "INCOMPLETE.txt").exists():
        raise ValueError("Backup is incomplete")
    for name, expected in manifest["artifacts"].items():
        if Path(name).name != name or name in ("", ".", ".."):
            raise ValueError("Invalid backup artifact name")
        path = folder / name
        if path.is_symlink() or not path.is_file() or digest(path) != expected["sha256"]:
            raise ValueError("Backup checksum mismatch")
    return manifest


def backup(repo, destination, mount=None):
    repo = repo.resolve()
    destination = destination.absolute()
    check_destination(destination, mount)
    roots = worktrees(repo)
    if not roots:
        raise ValueError("No working checkouts found")
    before = [worktree_state(root) for root in roots]
    refs = git(repo, "show-ref")
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="strike-source-backup-") as temporary:
        staging = Path(temporary)
        git(repo, "bundle", "create", str(staging / "repository.bundle"), "--all")
        git(repo, "bundle", "verify", str(staging / "repository.bundle"))
        details = []
        for number, (root, state) in enumerate(zip(roots, before), 1):
            prefix = f"worktree-{number:02d}"
            for field in ("index_patch", "working_patch", "status"):
                (staging / f"{prefix}-{field}").write_bytes(state[field])
            with tarfile.open(staging / f"{prefix}-source.tar.gz", "x:gz", dereference=False) as archive:
                for relative in state["files"]:
                    archive.add(root / relative, arcname=relative, recursive=False)
            # Verify the archived content itself, not only before/after source fingerprints.
            with tarfile.open(staging / f"{prefix}-source.tar.gz", "r:gz") as archive:
                for member in archive.getmembers():
                    expected = state["files"][member.name]
                    if member.issym():
                        if member.linkname != expected.get("link"):
                            raise ValueError("Source link changed during backup")
                    else:
                        result = hashlib.sha256()
                        with archive.extractfile(member) as stream:
                            for block in iter(lambda: stream.read(1024 * 1024), b""):
                                result.update(block)
                        if result.hexdigest() != expected.get("sha256"):
                            raise ValueError("Source file changed during backup")
            details.append({"root": str(root), "head": state["head"], "prefix": prefix,
                            "files": state["files"]})
        if roots != worktrees(repo) or refs != git(repo, "show-ref") or before != [worktree_state(root) for root in roots]:
            raise ValueError("Source changed during backup; no NAS backup published")
        artifacts = {p.name: {"sha256": digest(p), "bytes": p.stat().st_size} for p in staging.iterdir()}
        check_destination(destination, mount)
        destination.mkdir(parents=True, exist_ok=True)
        output = destination / name
        output.mkdir(mode=0o700)  # Exclusive; never replace an existing snapshot.
        try:
            for source in staging.iterdir():
                with source.open("rb") as reader, (output / source.name).open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
                    writer.flush()
                    os.fsync(writer.fileno())
                if digest(output / source.name) != artifacts[source.name]["sha256"]:
                    raise ValueError("NAS read-back checksum mismatch")
            check_destination(destination, mount)
            manifest = {"version": 1, "status": "complete", "worktrees": details,
                        "artifacts": artifacts, "exclusions": "Git-ignored files, caches and build products"}
            with (output / "manifest.json").open("x") as stream:
                json.dump(manifest, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            verify_backup(output)
        except Exception:
            # Retain partial artifacts for diagnosis; never remove another snapshot.
            with (output / "INCOMPLETE.txt").open("x") as stream:
                stream.write("Do not restore this backup. Publication or verification failed.\n")
            raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--require-mount", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        result = verify_backup(args.verify)
        print(f"Verified {len(result['artifacts'])} backup artifacts.")
    elif args.destination:
        print(backup(args.repo, args.destination, args.require_mount))
    else:
        parser.error("Choose --destination or --verify")


if __name__ == "__main__":
    main()
