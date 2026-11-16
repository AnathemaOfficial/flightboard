# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Text-plan caches must leave every current filesystem and Git safety check intact."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path, PurePosixPath
import tempfile
import unittest
from unittest import mock

from tests.fixtures import GIT, NOW, load
from tests.test_files import make_link
from tests.test_modes import Plain

files = load("files")
collector = load("collector")
Settings = load("config").Settings


class PathPlansTest(unittest.TestCase):
    def setUp(self) -> None:
        files._clear_path_plans()
        self.addCleanup(files._clear_path_plans)

    def test_repeated_names_reuse_only_an_immutable_text_plan(self) -> None:
        with mock.patch.object(files.os, "lstat", side_effect=AssertionError("filesystem lookup")), \
                mock.patch.object(files.os, "scandir", side_effect=AssertionError("directory lookup")):
            first = files._relative_plan("src/module/file.py")
            again = files._relative_plan("src/module/file.py")
        self.assertIs(first, again)
        self.assertEqual(first.parts, ("src", "module", "file.py"))
        self.assertEqual(first.parent, ("src", "module"))
        self.assertTrue(first.lexical)
        self.assertEqual(files._cached_relative_plan.cache_info().hits, 1)
        with self.assertRaises(AttributeError):
            first.lexical = False

    def test_name_cache_is_bounded_and_evicts_the_oldest_spelling(self) -> None:
        for number in range(files.PATH_PLAN_CACHE_SIZE + 1):
            files._relative_plan(f"module-{number}/file.py")
        info = files._cached_relative_plan.cache_info()
        self.assertEqual((info.maxsize, info.currsize), (files.PATH_PLAN_CACHE_SIZE, files.PATH_PLAN_CACHE_SIZE))
        files._relative_plan("module-0/file.py")
        self.assertEqual(files._cached_relative_plan.cache_info().misses, info.misses + 1)

    def test_oversized_names_are_computed_without_being_retained_or_refused(self) -> None:
        names = ["a" * (files.PATH_PLAN_NAME_CHARS + 1), "/".join(["part"] * (files.PATH_PLAN_COMPONENTS + 1))]
        for name in names:
            with self.subTest(name_length=len(name)):
                self.assertEqual(files._relative_plan(name).parts, PurePosixPath(name).parts)
                self.assertTrue(files.safe_relative(name))
        self.assertEqual(files._cached_relative_plan.cache_info().currsize, 0)

    def test_platform_device_and_encoding_policy_are_current_even_with_a_cached_name(self) -> None:
        name = "folder/nul/file.txt"
        with mock.patch.object(files.os, "name", "posix"):
            self.assertTrue(files.safe_relative(name))
        with mock.patch.object(files.os, "name", "nt"):
            self.assertFalse(files.safe_relative(name))
            ordinary = "folder/newdevice/file.txt"
            self.assertTrue(files.safe_relative(ordinary))
            with mock.patch.object(files, "RESERVED", files.RESERVED | {"NEWDEVICE"}):
                self.assertFalse(files.safe_relative(ordinary))
        cannot = UnicodeEncodeError("latin-1", "日本.txt", 0, 1, "not representable")
        with mock.patch.object(files.os, "name", "posix"), \
                mock.patch.object(files.os, "fsencode", side_effect=lambda value: value.encode("utf-8")) as encode:
            self.assertTrue(files.safe_relative("日本.txt"))
            encode.side_effect = cannot
            self.assertFalse(files.safe_relative("日本.txt"))
        self.assertGreater(files._cached_relative_plan.cache_info().hits, 0)

    def test_parent_plans_have_stable_order_and_are_bounded_under_concurrent_readers(self) -> None:
        names = {"src/lib/a.py", "src/b.py", "README.md"}
        first = files._parent_plan(names)
        self.assertEqual(first.known, frozenset({"src", "src/lib"}))
        self.assertEqual(first.ordered, (("", ()), ("src", ("src",)), ("src/lib", ("src", "lib"))))
        self.assertIs(first, files._parent_plan(set(names)))
        self.assertEqual(files._parent_plan_cache_info().hits, 1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            plans = list(pool.map(lambda _: files._parent_plan(set(names)), range(32)))
        self.assertTrue(all(plan is first for plan in plans))
        for number in range(files.PARENT_PLAN_CACHE_SIZE + 1):
            files._parent_plan({f"module-{number}/file.py"})
        info = files._parent_plan_cache_info()
        self.assertEqual(info.currsize, files.PARENT_PLAN_CACHE_SIZE)
        files._parent_plan(names)
        self.assertEqual(files._parent_plan_cache_info().misses, info.misses + 1)

    def test_large_parent_plans_are_not_retained(self) -> None:
        inputs = {
            "name count": {f"file-{number}.py" for number in range(files.PARENT_PLAN_NAMES + 1)},
            "text size": {f"dir/{number:03}/" + "x" * 600 for number in range(240)},
            "folder count": {f"a{number}/b{number}/c{number}/file.py" for number in range(1400)},
            "depth": {"/".join(["part"] * (files.PATH_PLAN_COMPONENTS + 1))},
            "name size": {"a" * (files.PATH_PLAN_NAME_CHARS + 1)},
        }
        for reason, names in inputs.items():
            files._clear_path_plans()
            with self.subTest(reason=reason):
                plan = files._parent_plan(names)
                expected = set()
                for name in names:
                    parent = PurePosixPath(name).parent
                    while str(parent) not in ("", "."):
                        expected.add(str(parent))
                        parent = parent.parent
                self.assertEqual(plan.known, frozenset(expected))
                self.assertEqual(files._parent_plan_cache_info().currsize, 0)

    def test_directory_contents_are_read_again_after_a_plan_hit_with_the_old_directory_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            folder = root / "src"
            folder.mkdir()
            (folder / "tracked.txt").write_text("tracked", encoding="utf-8")
            tracked = {"src/tracked.txt"}
            with mock.patch.object(files, "_entries", wraps=files._entries) as listing:
                self.assertEqual(files.untracked(root, root, tracked), [])
                original = folder.stat()
                (folder / "new.txt").write_text("new", encoding="utf-8")
                os.utime(folder, ns=(original.st_atime_ns, original.st_mtime_ns))
                self.assertEqual(files.untracked(root, root, tracked), ["src/new.txt"])
            self.assertEqual(listing.call_count, 4)  # root and src, each on both readings
            self.assertGreaterEqual(files._parent_plan_cache_info().hits, 1)

    @unittest.skipUnless(os.name == "nt", "Windows path-length policy")
    def test_current_path_length_limit_is_not_cached_with_the_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "file.py").write_text("x", encoding="utf-8")
            staged = [("100644", "file.py")]
            self.assertEqual(files.tracked_problem(root, root, staged), "")
            with mock.patch.object(files, "MAX_PATH", 1):
                self.assertEqual(files.tracked_problem(root, root, staged), "long_tracked_path")
            self.assertEqual(files.tracked_problem(root, root, staged), "")


@unittest.skipIf(GIT is None, "git absent")
class PathPlansGitFreshnessTest(unittest.TestCase):
    def setUp(self) -> None:
        files._clear_path_plans()
        self.addCleanup(files._clear_path_plans)
        self.repo = Plain()
        self.addCleanup(self.repo.close)

    def test_same_size_ignore_rule_with_its_old_time_is_read_again(self) -> None:
        self.repo.commit(self.repo.root, ".gitignore", "one.tmp\n", "ignore one file", "09:00")
        (self.repo.root / "one.tmp").write_text("new", encoding="utf-8")
        reader = collector.Collector(self.repo.root)
        first = reader.snapshot(NOW)["sessions"][0]
        self.assertTrue(first["files_read"])
        self.assertEqual(first["untracked"], 0)
        path = self.repo.root / ".gitignore"
        before = path.stat()
        path.write_text("two.tmp\n", encoding="utf-8", newline="\n")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(path.stat().st_size, before.st_size)
        self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
        second = reader.snapshot(NOW)["sessions"][0]
        self.assertTrue(second["files_read"])
        self.assertEqual(second["untracked"], 1)
        self.assertGreaterEqual(files._parent_plan_cache_info().hits, 1)

    def test_changed_index_names_are_rechecked_with_the_old_index_size_and_time(self) -> None:
        reader = collector.Collector(self.repo.root)
        self.assertTrue(reader.snapshot(NOW)["sessions"][0]["files_read"])
        path = self.repo.root / ".git" / "index"
        before = path.stat()
        data = path.read_bytes()
        body = data[:-20].replace(b"app.py\0", b"../bad\0", 1)
        self.assertNotEqual(body, data[:-20])
        path.write_bytes(body + hashlib.sha1(body).digest())
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(path.stat().st_size, before.st_size)
        with mock.patch.object(reader.git, "status", wraps=reader.git.status) as status:
            result = reader.snapshot(NOW)["sessions"][0]
        self.assertFalse(result["files_read"])
        self.assertNotIn(result.get("advice"), ("ready_to_merge", "ended"))
        status.assert_not_called()

    def test_a_cached_parent_plan_does_not_hide_a_new_link(self) -> None:
        self.repo.commit(self.repo.root, "src/file.py", "tracked\n", "track source file", "09:00")
        reader = collector.Collector(self.repo.root)
        self.assertTrue(reader.snapshot(NOW)["sessions"][0]["files_read"])
        folder = self.repo.root / "src"
        (folder / "file.py").unlink()
        folder.rmdir()
        outside = self.repo.root.parent / "outside"
        outside.mkdir()
        (outside / "file.py").write_text("outside", encoding="utf-8")
        if not make_link(outside, folder):
            self.skipTest("this system does not allow links or junctions")
        with mock.patch.object(reader.git, "status", wraps=reader.git.status) as status:
            result = reader.snapshot(NOW)["sessions"][0]
        self.assertFalse(result["files_read"])
        self.assertEqual(result["files_issue"], "tracked_link_folder")
        status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
