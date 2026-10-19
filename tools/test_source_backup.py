#!/usr/bin/env python3
"""Disposable repository restore, ignored-file, collision and corruption checks."""
import os
import ntpath
from pathlib import Path, PureWindowsPath
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

from backup_source import available_mount, backup, check_destination, git, verify_backup


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

    def test_drive_root_works_without_pathlib_windows_mount_support(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            # A real accessible drive root on Windows, / on Unix. Python 3.10/3.11
            # pathlib returns False on Windows; the os.path check must still work.
            with mock.patch.object(Path, "is_mount", return_value=False):
                check_destination(base / "backups", Path(base.anchor))
            self.assertFalse((base / "backups").exists(), "Validation must not create directories")

    def test_windows_drive_and_unc_roots_require_a_reachable_directory(self):
        windows_ismount = ntpath.ismount
        for root in (PureWindowsPath("Z:/"), PureWindowsPath("//backup.invalid/strike")):
            with self.subTest(root=str(root)):
                # Exercise Windows root recognition on every CI platform without
                # contacting a real network share or mounting a developer drive.
                with mock.patch("backup_source.os.path.ismount", side_effect=windows_ismount):
                    with mock.patch("backup_source.os.path.isdir", return_value=True):
                        self.assertTrue(available_mount(root))
                    with mock.patch("backup_source.os.path.isdir", return_value=False):
                        self.assertFalse(available_mount(root), "Disconnected roots are not available mounts")

    def test_required_mount_rejects_ordinary_folder_and_outside_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            with self.assertRaisesRegex(ValueError, "mount"):
                check_destination(base / "backups", base)
            with mock.patch("backup_source.available_mount", return_value=True):
                with self.assertRaisesRegex(ValueError, "mount"):
                    check_destination(base / "backups", base / "different-share")
            self.assertFalse((base / "backups").exists())

    def test_missing_mount_never_creates_a_local_shadow_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            destination = base / "missing-nas" / "backups"
            with self.assertRaisesRegex(ValueError, "mount"):
                backup(base, destination, base / "missing-nas")
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
