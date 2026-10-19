#!/usr/bin/env python3
"""Disposable repository restore, ignored-file, collision and corruption checks."""
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from backup_source import backup, git, verify_backup


class SourceBackupTests(unittest.TestCase):
    def test_restore_all_branches_and_dirty_binary_text_and_untracked_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            repo = base / "repo"
            repo.mkdir()
            git(repo, "init", "-b", "main")
            git(repo, "config", "user.name", "Backup test")
            git(repo, "config", "user.email", "backup@example.invalid")
            (repo / ".gitignore").write_text("ignored/\n")
            (repo / "text.txt").write_text("committed\n")
            (repo / "delete.txt").write_text("delete later\n")
            (repo / "binary.dat").write_bytes(bytes(range(256)))
            git(repo, "add", ".")
            git(repo, "commit", "-m", "Initial")
            second = base / "second"
            git(repo, "worktree", "add", "-b", "codex/prototype", str(second))
            (second / "prototype.txt").write_text("unfinished prototype\n")
            (repo / "text.txt").write_text("staged\n")
            git(repo, "add", "text.txt")
            (repo / "text.txt").write_text("working\n")
            (repo / "delete.txt").unlink()
            (repo / "binary.dat").write_bytes(b"\x00\xffchanged\n")
            (repo / "untracked.txt").write_text("unsaved to Git\n")
            (repo / "ignored").mkdir()
            (repo / "ignored" / "credential").write_text("excluded\n")
            if os.name != "nt":
                (repo / "external-link").symlink_to(base / "outside")
            status = git(repo, "status", "--porcelain=v1")
            output = backup(repo, base / "backups")
            report = verify_backup(output)
            self.assertEqual(len(report["worktrees"]), 2)
            self.assertEqual(git(repo, "status", "--porcelain=v1"), status)
            restored = base / "restored"
            subprocess.run(["git", "clone", str(output / "repository.bundle"), str(restored)],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertIn(b"codex/prototype", git(restored, "branch", "-a"))
            git(restored, "apply", "--index", str(output / "worktree-01-index_patch"))
            git(restored, "apply", str(output / "worktree-01-working_patch"))
            self.assertEqual((restored / "text.txt").read_text(), "working\n")
            self.assertEqual((restored / "binary.dat").read_bytes(), b"\x00\xffchanged\n")
            self.assertFalse((restored / "delete.txt").exists())
            with tarfile.open(output / "worktree-01-source.tar.gz") as archive:
                self.assertNotIn("ignored/credential", archive.getnames())
                self.assertEqual(archive.extractfile("untracked.txt").read(), b"unsaved to Git\n")
                if os.name != "nt":
                    self.assertTrue(archive.getmember("external-link").issym())
            with tarfile.open(output / "worktree-02-source.tar.gz") as archive:
                self.assertEqual(archive.extractfile("prototype.txt").read(), b"unfinished prototype\n")
            second_backup = backup(repo, base / "backups")
            self.assertNotEqual(output, second_backup)
            verify_backup(output)
            (output / "repository.bundle").write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "checksum"):
                verify_backup(output)

    def test_missing_mount_never_creates_a_local_shadow_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            destination = base / "missing-nas" / "backups"
            with self.assertRaisesRegex(ValueError, "mount"):
                backup(base, destination, base / "missing-nas")
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
