# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Release publication is exact-SHA, complete-before-visible and idempotent."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests.fixtures import ROOT

SPEC = importlib.util.spec_from_file_location("release_publish", ROOT / "tools" / "publish_release.py")
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)
SHA = "a" * 40
REPOSITORY = "example/flightboard"
VERSION = "0.2.12"


class FakeGh:
    def __init__(self, files, *, release=None, tag=None, main=SHA):
        self.files = files
        self.release = copy.deepcopy(release)
        self.tag = tag
        self.main = main
        self.calls = []

    def get(self, endpoint, *, optional=False):
        self.calls.append(("GET", endpoint))
        if endpoint.endswith("git/ref/heads/main"):
            return {"object": {"type": "commit", "sha": self.main}}
        if "/git/ref/tags/" in endpoint:
            return None if self.tag is None else {"object": {"type": "commit", "sha": self.tag}}
        if "/releases/tags/" in endpoint:
            return copy.deepcopy(self.release) if self.release and not self.release["draft"] else None
        if endpoint.endswith("/releases/123"):
            return copy.deepcopy(self.release)
        raise AssertionError(endpoint)

    def pending_release_id(self, repository, tag):
        self.calls.append(("DRAFT", repository, tag))
        return 123 if self.release and self.release["draft"] else None

    def run(self, *arguments):
        self.calls.append(tuple(arguments))
        operation = arguments[1]
        if operation == "create":
            self.release = {"draft": True, "prerelease": False, "target_commitish": SHA, "assets": []}
        elif operation == "upload":
            paths = arguments[3:arguments.index("--repo")]
            for value in paths:
                path = Path(value)
                self.release["assets"].append(self.asset(path.name))
        elif operation == "edit":
            self.release["draft"] = False
            self.tag = SHA
        else:
            raise AssertionError(arguments)

    def asset(self, name):
        raw = self.files[name]
        return {"name": name, "size": len(raw), "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "state": "uploaded"}


class PublishReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.files = {f"flightboard-skill-{VERSION}.zip": b"skill", f"flightboard-plugin-{VERSION}.zip": b"plugin"}
        manifest = {"schema_version": 1, "source_sha": SHA, "version": VERSION, "source_base_version": "0.2.0",
                    "assets": [{"name": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                               for name, raw in self.files.items()]}
        self.files["release-manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
        self.files["SHA256SUMS"] = "".join(hashlib.sha256(raw).hexdigest() + "  " + name + "\n"
                                            for name, raw in sorted(self.files.items())).encode()
        for name, raw in self.files.items():
            (self.folder / name).write_bytes(raw)

    def publish(self, gh):
        return publisher.publish(self.folder, VERSION, SHA, REPOSITORY, gh=gh)

    def test_new_release_is_verified_draft_before_publication(self):
        gh = FakeGh(self.files)
        found = self.publish(gh)
        writes = [call for call in gh.calls if call[0] == "release"]
        self.assertEqual([call[1] for call in writes], ["create", "upload", "edit"])
        self.assertIn("--draft", writes[0])
        self.assertIn(SHA, writes[0])
        self.assertIn("--latest=true", writes[-1])
        self.assertEqual(found["status"], "published")

    def test_old_main_build_cannot_become_latest(self):
        gh = FakeGh(self.files, main="b" * 40)
        self.publish(gh)
        self.assertIn("--latest=false", next(call for call in gh.calls if call[:2] == ("release", "edit")))

    def test_identical_published_rerun_makes_no_mutations(self):
        gh = FakeGh(self.files, tag=SHA)
        gh.release = {"draft": False, "prerelease": False, "assets": [gh.asset(name) for name in self.files]}
        found = self.publish(gh)
        self.assertEqual(found["status"], "already_published")
        self.assertFalse([call for call in gh.calls if call[0] == "release"])

    def test_partial_draft_rerun_uploads_only_missing_assets(self):
        gh = FakeGh(self.files)
        gh.release = {"draft": True, "prerelease": False, "target_commitish": SHA,
                      "assets": [gh.asset("SHA256SUMS")]}
        self.publish(gh)
        upload = next(call for call in gh.calls if call[:2] == ("release", "upload"))
        self.assertNotIn(str(self.folder / "SHA256SUMS"), upload)
        self.assertEqual(len(gh.release["assets"]), 4)

    def test_wrong_existing_tag_or_asset_is_never_clobbered(self):
        for bad_tag in (True, False):
            with self.subTest(bad_tag=bad_tag):
                gh = FakeGh(self.files, tag="b" * 40 if bad_tag else SHA)
                gh.release = {"draft": False, "prerelease": False,
                              "assets": [gh.asset(name) for name in self.files]}
                if not bad_tag:
                    gh.release["assets"][0]["digest"] = "sha256:" + "0" * 64
                with self.assertRaises(publisher.PublishError):
                    self.publish(gh)
                self.assertFalse([call for call in gh.calls if call[0] == "release"])

    def test_local_tampering_and_manifest_mismatch_fail_before_network(self):
        (self.folder / f"flightboard-skill-{VERSION}.zip").write_bytes(b"tampered")
        gh = FakeGh(self.files)
        with self.assertRaises(publisher.PublishError):
            self.publish(gh)
        self.assertFalse(gh.calls)

    def test_missing_remote_digest_is_not_assumed_identical(self):
        gh = FakeGh(self.files, tag=SHA)
        gh.release = {"draft": False, "prerelease": False, "assets": [gh.asset(name) for name in self.files]}
        gh.release["assets"][0]["digest"] = None
        with self.assertRaises(publisher.PublishError):
            self.publish(gh)
        self.assertFalse([call for call in gh.calls if call[0] == "release"])

    def test_malformed_or_mismatched_manifest_fails_before_network(self):
        path = self.folder / "release-manifest.json"
        initial = json.loads(path.read_text())
        for changes in ({"version": "0.2.99"}, {"source_sha": "b" * 40}, {"schema_version": True},
                        {"assets": [{"name": "../payload.zip"}, {"name": "outside.zip"}]}):
            with self.subTest(changes=changes):
                path.write_text(json.dumps({**initial, **changes}), encoding="utf-8")
                gh = FakeGh(self.files)
                with self.assertRaises(publisher.PublishError):
                    self.publish(gh)
                self.assertFalse(gh.calls)

    def test_failed_upload_keeps_release_unpublished(self):
        gh = FakeGh(self.files)
        actual = gh.run

        def run(*arguments):
            if arguments[:2] == ("release", "upload"):
                raise publisher.PublishError("failed upload")
            return actual(*arguments)

        gh.run = run
        with self.assertRaises(publisher.PublishError):
            self.publish(gh)
        self.assertTrue(gh.release["draft"])
        self.assertFalse([call for call in gh.calls if call[:2] == ("release", "edit")])


class GhClientTest(unittest.TestCase):
    def test_pending_draft_lookup_uses_graphql_then_validates_identity(self):
        body = {"data": {"repository": {"release": {"databaseId": 123, "isDraft": True,
                                                      "tagName": "v" + VERSION}}}}
        runner = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(body).encode(), stderr=b""))
        self.assertEqual(publisher.Gh(runner).pending_release_id(REPOSITORY, "v" + VERSION), 123)
        self.assertIn("graphql", runner.call_args.args[0])
        for changes in ({"isDraft": False}, {"databaseId": True}, {"tagName": "v9.0.0"}):
            with self.subTest(changes=changes):
                altered = copy.deepcopy(body)
                altered["data"]["repository"]["release"].update(changes)
                runner.return_value.stdout = json.dumps(altered).encode()
                with self.assertRaises(publisher.PublishError):
                    publisher.Gh(runner).pending_release_id(REPOSITORY, "v" + VERSION)

    def test_get_is_fixed_host_explicit_get_and_bounded_process(self):
        runner = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=b'{"ok":true}', stderr=b""))
        found = publisher.Gh(runner).get("repos/example/repository")
        self.assertEqual(found, {"ok": True})
        arguments, options = runner.call_args
        self.assertEqual(arguments[0][:6], ["gh", "api", "--hostname", "github.com", "--method", "GET"])
        self.assertEqual(options["timeout"], 90)
        self.assertTrue(options["capture_output"])

    def test_only_explicit_optional_404_is_absence_and_errors_do_not_echo_body(self):
        response = SimpleNamespace(returncode=1, stdout=b"", stderr=b"secret sentinel HTTP 404")
        client = publisher.Gh(mock.Mock(return_value=response))
        self.assertIsNone(client.get("repos/example/repo", optional=True))
        with self.assertRaises(publisher.PublishError) as error:
            client.get("repos/example/repo")
        self.assertNotIn("secret sentinel", str(error.exception))
        response.stderr = b"HTTP 403"
        with self.assertRaises(publisher.PublishError):
            client.get("repos/example/repo", optional=True)


class ReleaseWorkflowTest(unittest.TestCase):
    def test_only_validated_main_has_write_permission(self):
        source = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("needs: [tests, plugin, licensing, package]", source)
        release = source.split("  release:\n", 1)[1]
        self.assertIn("github.event_name == 'push' && github.ref == 'refs/heads/main'", release)
        self.assertIn("contents: write", release)
        self.assertIn("cancel-in-progress: false", release)
        self.assertIn("queue: max", release)
        self.assertIn("group: ci-${{ github.event_name == 'push' && github.sha || github.ref }}", source)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", source)
        self.assertNotIn("pull_request_target", source)


if __name__ == "__main__":
    unittest.main()
