# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Conservative session verdicts, exercised on real Git repositories and worktrees."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import GIT, NOW, load
from tests.test_modes import Plain

collector_module = load("collector")
gitreads = load("gitreads")
Settings = load("config").Settings


def by_name(found: dict) -> dict[str, dict]:
    return {card["name"]: card for card in found["sessions"]}


@unittest.skipIf(GIT is None, "git absent")
class PortedSessionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.ledger = {"tasks": [{"id": "APP-1", "title": "One", "status": "planned", "owner": "codex"}]}
        self.repo.commit(self.repo.root, "tasks.json", self.body(), "tasks", "08:40")

    def body(self) -> str:
        return json.dumps(self.ledger)

    def read(self, **settings) -> dict:
        return collector_module.Collector(self.repo.root, Settings(**settings)).snapshot(NOW)

    def ready(self, name: str = "work", branch: str = "codex/app-1") -> Path:
        where = self.repo.worktree(name, branch)
        self.ledger["tasks"][0]["status"] = "awaiting_review"
        self.repo.commit(where, "tasks.json", self.body(), "feat: APP-1", "09:00")
        return where

    def test_stash_tied_to_a_worktree_blocks_ready_and_ended(self) -> None:
        where = self.ready()
        self.assertEqual(by_name(self.read())["work"]["advice"], "ready_to_merge")
        (where / "app.py").write_text("parked\n", encoding="utf-8")
        self.repo.git("stash", "push", "-m", "parked", where=where)
        card = by_name(self.read())["work"]
        self.assertEqual(card["stash"], "stashed")
        self.assertNotIn(card["advice"], ("ready_to_merge", "ended"))
        self.ledger["tasks"][0]["status"] = "done"
        self.repo.commit(where, "tasks.json", self.body(), "done: APP-1", "09:10")
        self.repo.git("merge", "-q", "--ff-only", "codex/app-1")
        card = by_name(self.read())["work"]
        self.assertEqual(card["stash"], "stashed")
        self.assertNotEqual(card["advice"], "ended")

    def test_unmatched_and_unreadable_stash_hold_every_card(self) -> None:
        where = self.ready()
        (where / "app.py").write_text("parked\n", encoding="utf-8")
        self.repo.git("stash", "push", "-m", "parked", where=where)
        stash = self.repo.git("rev-parse", "refs/stash")
        self.repo.git("stash", "clear")
        self.repo.git("stash", "store", "-m", "opaque stash", stash)
        cards = self.read()["sessions"]
        self.assertTrue(cards)
        self.assertTrue(all(card["stash"] == "unmatched" for card in cards))
        self.assertFalse(any(card["advice"] in ("ready_to_merge", "ended") for card in cards))
        log = self.repo.root / ".git" / "logs" / "refs" / "stash"
        with log.open("ab") as stream:
            stream.write(b"not a reflog entry\n")
        self.assertTrue(all(card["stash"] == "unknown" for card in self.read()["sessions"]))

    def test_a_detached_commit_left_behind_is_counted_until_a_branch_holds_it(self) -> None:
        where = self.ready()
        self.repo.git("checkout", "-q", "--detach", where=where)
        self.repo.commit(where, "detached.txt", "keep me\n", "detached work", "09:20")
        lost = self.repo.git("rev-parse", "HEAD", where=where)
        self.repo.git("checkout", "-q", "codex/app-1", where=where)
        collector = collector_module.Collector(self.repo.root)
        card = by_name(collector.snapshot(NOW))["work"]
        self.assertEqual(card["left_behind"], 1)
        self.assertNotIn(card["advice"], ("ready_to_merge", "ended"))
        self.repo.git("branch", "saved-detached", lost)
        card = by_name(collector.snapshot(NOW))["work"]
        self.assertEqual(card["left_behind"], 0)
        self.assertEqual(card["advice"], "ready_to_merge")

    def test_an_incomplete_or_truncated_head_reflog_cannot_hide_detached_work(self) -> None:
        where = self.ready()
        self.repo.git("checkout", "-q", "--detach", where=where)
        self.repo.commit(where, "detached.txt", "keep me\n", "detached work", "09:20")
        self.repo.git("checkout", "-q", "codex/app-1", where=where)
        log = self.repo.root / ".git" / "worktrees" / "work" / "logs" / "HEAD"
        complete = log.read_bytes()
        log.write_bytes(complete[:-1])
        card = by_name(self.read())["work"]
        self.assertEqual(card["files_issue"], "head_log_unreadable")
        self.assertNotIn(card["advice"], ("ready_to_merge", "ended"))
        log.write_bytes(complete)
        with mock.patch.object(load("held"), "MAX_MOVES", 1):
            card = by_name(self.read())["work"]
        self.assertEqual(card["files_issue"], "head_log_unreadable")
        self.assertNotIn(card["advice"], ("ready_to_merge", "ended"))

    def test_a_symbolic_branch_with_worktree_local_target_is_unknown(self) -> None:
        where = self.ready()
        own = self.repo.git("rev-parse", "HEAD", where=where)
        main = self.repo.git("rev-parse", "main")
        self.repo.git("update-ref", "refs/worktree/private", main)
        self.repo.git("update-ref", "refs/worktree/private", own, where=where)
        self.repo.git("symbolic-ref", "refs/heads/codex/app-1", "refs/worktree/private")
        found = self.read()
        self.assertEqual(found["main"]["state"], "ok")
        card = by_name(found)["work"]
        self.assertEqual(card["reason"], "head_symbolic")
        self.assertFalse(card["files_read"])
        self.assertIsNone(card["ahead"])
        self.assertNotIn(card["advice"], ("ready_to_merge", "ended"))

    def test_remote_copy_is_held_by_a_dirty_or_unread_local_worktree(self) -> None:
        where = self.ready()
        tip = self.repo.git("rev-parse", "HEAD", where=where)
        self.repo.git("update-ref", "refs/remotes/upstream/codex/app-1", tip)
        self.repo.git("reset", "-q", "--hard", "main", where=where)
        (where / "app.py").write_text("new local work\n", encoding="utf-8")
        collector = collector_module.Collector(self.repo.root, Settings(remote="upstream"))
        card = by_name(collector.snapshot(NOW))["upstream/codex/app-1"]
        self.assertEqual((card["held"], card["reason"]), ("held_worktree", "held_worktree"))
        self.assertFalse(card["overlay"])
        self.assertNotEqual(card["advice"], "ready_to_merge")
        self.repo.git("reset", "-q", "--hard", "main", where=where)
        (self.repo.root / ".git" / "worktrees" / "work" / "index").write_bytes(b"invalid index")
        cards = by_name(collector.snapshot(NOW))
        self.assertFalse(cards["work"]["files_read"])
        self.assertEqual(cards["upstream/codex/app-1"]["held"], "held_worktree")

    def test_casefold_ambiguous_refs_stop_the_reading(self) -> None:
        self.repo.git("pack-refs", "--all")
        self.repo.git("update-ref", "refs/heads/Main", self.repo.git("rev-parse", "main"))
        found = self.read()
        self.assertEqual((found["main"]["state"], found["main"]["reason"]), ("unreadable", "ambiguous_refs"))

    def test_forged_main_reflog_entry_never_enters_main_history(self) -> None:
        where = self.ready()
        tip = self.repo.git("rev-parse", "HEAD", where=where)
        main = self.repo.git("rev-parse", "main")
        log = self.repo.root / ".git" / "logs" / "refs" / "heads" / "main"
        with log.open("ab") as stream:
            stream.write(f"{main} {tip} Test <test@example.com> {int(NOW.timestamp())} -0500\tforged main move\n".encode())
        found = self.read()
        self.assertEqual(found["main"]["head"], main[:7])
        self.assertNotIn(tip[:7], [move["sha"] for move in found["moves"]])
        self.assertFalse(any("forged" in move["via"] for move in found["moves"]))

    def test_working_ledger_cache_uses_bytes_even_when_identity_is_restored(self) -> None:
        where = self.repo.worktree("work", "codex/app-1")
        self.repo.commit(where, "feature.txt", "feature\n", "feature APP-1", "09:00")
        collector = collector_module.Collector(self.repo.root)
        collector.snapshot(NOW)
        path = where / "tasks.json"
        old = path.stat()
        data = path.read_bytes().replace(b'"planned"', b'"blocked"')
        self.assertEqual(len(data), old.st_size)
        path.write_bytes(data)
        os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
        card = by_name(collector.snapshot(NOW))["work"]
        self.assertEqual([(change["task"], change["to"]) for change in card["changes"]], [("APP-1", "blocked")])

    def test_failed_session_reading_never_reuses_a_ready_card(self) -> None:
        where = self.ready()
        collector = collector_module.Collector(self.repo.root)
        self.assertEqual(by_name(collector.snapshot(NOW))["work"]["advice"], "ready_to_merge")
        (where / "app.py").write_text("more work\n", encoding="utf-8")
        original = collector.git.status

        def failing(git_dir, work_tree):
            if work_tree == where:
                raise gitreads.GitFailed("unreadable now")
            return original(git_dir, work_tree)

        with mock.patch.object(collector.git, "status", side_effect=failing):
            card = by_name(collector.snapshot(NOW))["work"]
        self.assertFalse(card["files_read"])
        self.assertNotEqual(card["advice"], "ready_to_merge")
        card = by_name(collector.snapshot(NOW))["work"]
        self.assertTrue(card["files_read"])
        self.assertEqual(card["modified"], 1)

    def test_uncommitted_ledger_changes_block_ready_when_git_trusts_restored_metadata(self) -> None:
        where = self.repo.worktree("work", "codex/app-1")
        self.repo.commit(where, "feature.txt", "feature\n", "feature APP-1", "09:00")
        self.repo.git("config", "core.trustctime", "false")
        path = where / "tasks.json"
        stamp = int(NOW.timestamp()) - 3600
        os.utime(path, (stamp, stamp))
        self.repo.git("update-index", "--refresh", where=where)
        collector = collector_module.Collector(self.repo.root)
        collector.snapshot(NOW)
        old = path.stat()
        data = path.read_bytes().replace(b'"planned"', b'"done"   ')
        self.assertEqual(len(data), old.st_size)
        path.write_bytes(data)
        os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
        self.assertEqual(self.repo.git("status", "--porcelain", "--untracked-files=no", where=where), "")
        card = by_name(collector.snapshot(NOW))["work"]
        self.assertTrue(card["changes"][0]["uncommitted"])
        self.assertEqual(card["stage"], "uncommitted")
        self.assertNotEqual(card["advice"], "ready_to_merge")

    def test_all_inferred_tasks_participate_in_readiness(self) -> None:
        self.ledger = {"tasks": [{"id": f"APP-{n}", "title": str(n), "status": "awaiting_review" if n < 5 else
                                  "planned", "owner": "codex"} for n in range(1, 6)]}
        self.repo.commit(self.repo.root, "tasks.json", self.body(), "more tasks", "08:45")
        where = self.repo.worktree("work", "codex/app-1-app-2-app-3-app-4-app-5")
        self.repo.commit(where, "feature.txt", "feature\n", "feature", "09:00")
        card = by_name(self.read())["work"]
        self.assertEqual(set(card["tasks"]), {f"APP-{n}" for n in range(1, 6)})
        self.assertEqual(len(card["inferred"]), 3)
        self.assertNotEqual(card["advice"], "ready_to_merge")

    def test_inference_reads_past_the_eight_commits_shown_on_the_card(self) -> None:
        self.ledger["tasks"].append({"id": "APP-2", "title": "Two", "status": "planned", "owner": "codex"})
        self.repo.commit(self.repo.root, "tasks.json", self.body(), "more tasks", "08:45")
        where = self.repo.worktree("work", "codex/feature")
        self.ledger["tasks"][0]["status"] = "awaiting_review"
        self.repo.commit(where, "tasks.json", self.body(), "APP-2 was started here", "09:00")
        for index in range(8):
            self.repo.commit(where, f"feature-{index}.txt", str(index), "APP-1 review", "09:10")
        card = by_name(self.read())["work"]
        self.assertEqual(len(card["commits"]), 8)
        self.assertEqual(set(card["tasks"]), {"APP-1", "APP-2"})
        self.assertEqual(card["reason"], "")
        self.assertNotEqual(card["advice"], "ready_to_merge")

    def test_a_failed_commit_range_blocks_ready_and_is_retried(self) -> None:
        self.ready()
        collector = collector_module.Collector(self.repo.root)
        with mock.patch.object(collector.git, "commits", side_effect=gitreads.GitFailed("range unreadable")):
            card = by_name(collector.snapshot(NOW))["work"]
        self.assertEqual(card["reason"], "commit_history_unreadable")
        self.assertNotEqual(card["advice"], "ready_to_merge")
        card = by_name(collector.snapshot(NOW))["work"]
        self.assertEqual((card["reason"], card["advice"]), ("", "ready_to_merge"))

    def test_a_cut_commit_range_blocks_ready(self) -> None:
        where = self.ready()
        for index in range(3):
            self.repo.commit(where, f"feature-{index}.txt", str(index), "APP-1 review", "09:10")
        with mock.patch.object(gitreads, "MAX_SESSION_COMMITS", 3):
            card = by_name(self.read())["work"]
        self.assertEqual(card["reason"], "commit_history_cut")
        self.assertNotEqual(card["advice"], "ready_to_merge")

    def test_an_incomplete_commit_log_cannot_look_like_a_complete_range(self) -> None:
        self.ready()
        collector = collector_module.Collector(self.repo.root)
        with mock.patch.object(collector.git, "commits", return_value=[]):
            card = by_name(collector.snapshot(NOW))["work"]
        self.assertEqual(card["reason"], "commit_history_unreadable")
        self.assertNotEqual(card["advice"], "ready_to_merge")
        self.assertEqual(by_name(collector.snapshot(NOW))["work"]["advice"], "ready_to_merge")

    def test_a_cut_merged_branch_reflog_cannot_establish_ended(self) -> None:
        where = self.ready()
        self.ledger["tasks"][0]["status"] = "done"
        self.repo.commit(where, "tasks.json", self.body(), "APP-1 done", "09:10")
        self.repo.git("merge", "-q", "--ff-only", "codex/app-1")
        self.assertEqual(by_name(self.read())["work"]["advice"], "ended")
        with mock.patch.object(gitreads, "MAX_SESSION_COMMITS", 2):
            card = by_name(self.read())["work"]
        self.assertEqual(card["reason"], "commit_history_unreadable")
        self.assertNotEqual(card["advice"], "ended")

    def test_inference_reads_beyond_the_short_display_subject(self) -> None:
        self.ledger["tasks"].append({"id": "APP-2", "title": "Two", "status": "planned", "owner": "codex"})
        self.repo.commit(self.repo.root, "tasks.json", self.body(), "more tasks", "08:45")
        where = self.repo.worktree("work", "codex/feature")
        self.ledger["tasks"][0]["status"] = "awaiting_review"
        self.repo.commit(where, "tasks.json", self.body(), "APP-1 " + "x" * 550 + " APP-2", "09:00")
        card = by_name(self.read())["work"]
        self.assertNotIn("APP-2", card["commits"][0]["subject"])
        self.assertIn("APP-2", card["tasks"])
        self.assertNotEqual(card["advice"], "ready_to_merge")

    def test_an_overlong_commit_subject_marks_inference_incomplete(self) -> None:
        where = self.ready()
        self.repo.commit(where, "feature.txt", "feature\n", "APP-1 " + "x" * gitreads.MAX_COMMIT_SUBJECT, "09:10")
        card = by_name(self.read())["work"]
        self.assertEqual(card["reason"], "commit_history_cut")
        self.assertNotEqual(card["advice"], "ready_to_merge")

    def test_same_named_external_worktrees_keep_distinct_applied_moves(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            external = Path(folder).resolve() / "agents"
            for group in ("a", "b"):
                (external / group).mkdir(parents=True)
            first, second = external / "a" / "plain", external / "b" / "plain"
            self.repo.git("worktree", "add", "-q", "-b", "codex/first", str(first), "main")
            self.repo.git("worktree", "add", "-q", "-b", "codex/second", str(second), "main")
            self.ledger["tasks"][0]["status"] = "done"
            self.repo.commit(first, "tasks.json", self.body(), "APP-1 done", "09:00")
            self.ledger["tasks"][0].update(status="awaiting_review", depends_on=["MISSING"])
            self.repo.commit(second, "tasks.json", self.body(), "APP-1 review, invalid claim", "10:00")
            found = self.read(external_worktrees=(external,))
            cards = [card for card in found["sessions"] if card["kind"] == "worktree"]
            self.assertEqual([card["name"] for card in cards], ["plain", "plain"])
            self.assertEqual(len({card["id"] for card in cards}), 2)
            self.assertEqual(found["tasks"]["APP-1"]["status"], "done")
            self.assertEqual({event["session_id"] for event in found["events"] if "session_id" in event},
                             {card["id"] for card in cards})
            self.assertEqual(sum(day["done_live"] for day in found["daily"]), 1)
            self.assertEqual(sum(day["review_live"] for day in found["daily"]), 0)

    def test_only_capped_branches_pay_for_remote_comparisons(self) -> None:
        where = self.ready()
        tip = self.repo.git("rev-parse", "HEAD", where=where)
        for n in range(15):
            self.repo.git("update-ref", f"refs/heads/extra-{n}", tip)
        collector = collector_module.Collector(self.repo.root, Settings(max_branches=2))
        with mock.patch.object(collector, "_remote", wraps=collector._remote) as remote:
            found = collector.snapshot(NOW)
        compared = [call for call in remote.call_args_list if (call.args[1] or "").startswith("refs/heads/extra-")]
        self.assertEqual(len(compared), 2)
        self.assertEqual(found["limits"]["branches_cut"], 13)

    def test_deadline_is_set_and_cleared_after_a_reading_failure(self) -> None:
        collector = collector_module.Collector(self.repo.root)

        def fail(now, mode):
            self.assertIsNotNone(collector.git.deadline)
            raise gitreads.GitFailed("deadline exhausted")

        with mock.patch.object(collector, "_snapshot", side_effect=fail):
            found = collector.snapshot(NOW)
        self.assertIsNone(collector.git.deadline)
        self.assertEqual(found["main"]["state"], "unreadable")

    def test_external_root_is_explicit_and_reads_working_bytes_under_its_boundary(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            external = Path(folder).resolve() / "agents"
            external.mkdir()
            where = external / "work"
            self.repo.git("worktree", "add", "-q", "-b", "codex/external", str(where), "main")
            self.ledger["tasks"][0]["status"] = "blocked"
            (where / "tasks.json").write_text(self.body(), encoding="utf-8")
            (where / "app.py").write_text("external edit\n", encoding="utf-8")
            (where / "new.txt").write_text("new\n", encoding="utf-8")
            self.assertEqual(by_name(self.read())["work"]["reason"], "outside")
            found = collector_module.Collector(self.repo.root, Settings(external_worktrees=(external,))).snapshot(NOW)
            card = by_name(found)["work"]
            self.assertEqual(card["reason"], "")
            self.assertTrue(card["files_read"])
            self.assertEqual((card["modified"], card["untracked"]), (2, 1))
            self.assertEqual(card["changes"][0]["to"], "blocked")
            self.assertNotIn(str(external), json.dumps(found))


if __name__ == "__main__":
    unittest.main()
