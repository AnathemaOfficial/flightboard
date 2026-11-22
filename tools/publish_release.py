# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Publish verified packages from a validated main commit, without replacing tags or assets.

The CI job alone grants this tool a write token, after every validation job passes.
New releases stay drafts until all four immutable assets have verified server digests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import tempfile

SHA = re.compile(r"[0-9a-f]{40}")
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}")
MAX_ASSET_BYTES = 32_000_000
MAX_JSON_BYTES = 1_000_000


class PublishError(ValueError):
    """Publication cannot prove the expected source and package identities."""


class Gh:
    """Fixed-host GitHub CLI calls; API failures never echo credentials or remote bodies."""

    def __init__(self, runner=subprocess.run):
        self.runner = runner

    def _run(self, arguments):
        try:
            return self.runner(["gh", *arguments], capture_output=True, timeout=90, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise PublishError("GitHub request failed") from exc

    def get(self, endpoint, *, optional=False):
        result = self._run(["api", "--hostname", "github.com", "--method", "GET", endpoint])
        if result.returncode:
            if optional and b"HTTP 404" in result.stderr:
                return None
            raise PublishError("GitHub metadata request failed")
        if len(result.stdout) > MAX_JSON_BYTES:
            raise PublishError("GitHub metadata too large")
        try:
            return json.loads(result.stdout)
        except (ValueError, UnicodeError) as exc:
            raise PublishError("Invalid GitHub metadata") from exc

    def run(self, *arguments):
        if self._run(list(arguments)).returncode:
            raise PublishError("GitHub release operation failed; a partial draft may remain")

    def pending_release_id(self, repository, tag):
        """Drafts have pending tags; REST by-tag lookup cannot find them before publication."""
        owner, name = repository.split("/")
        query = ("query($owner:String!,$name:String!,$tag:String!){repository(owner:$owner,name:$name)"
                 "{release(tagName:$tag){databaseId isDraft tagName}}}")
        result = self._run(["api", "--hostname", "github.com", "graphql", "-f", "query=" + query,
                            "-f", "owner=" + owner, "-f", "name=" + name, "-f", "tag=" + tag])
        if result.returncode or len(result.stdout) > MAX_JSON_BYTES:
            raise PublishError("Draft release lookup failed")
        try:
            response = json.loads(result.stdout)
            if response.get("errors"):
                raise PublishError("Draft release lookup failed")
            release = response["data"]["repository"]["release"]
            if release is None:
                return None
            if (not isinstance(release, dict) or type(release.get("databaseId")) is not int
                    or release["databaseId"] <= 0 or release.get("isDraft") is not True
                    or release.get("tagName") != tag):
                raise PublishError("Draft release identity mismatch")
            return release["databaseId"]
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise PublishError("Invalid draft release metadata") from exc


def _plain_bytes(path: Path, maximum: int) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 \
            or getattr(info, "st_file_attributes", 0) & 0x400 or info.st_size > maximum:
        raise PublishError("Package file is not an ordinary bounded file")
    raw = path.read_bytes()
    if len(raw) != info.st_size or len(raw) > maximum:
        raise PublishError("Package file changed while reading")
    return raw


def packages(directory: Path, version: str, revision: str) -> dict[str, dict]:
    """Validate the builder contract before issuing any network request."""
    if VERSION.fullmatch(version) is None or SHA.fullmatch(revision) is None:
        raise PublishError("Expected a stable semantic version and full commit SHA")
    directory = Path(directory).absolute()
    try:
        for parent in (directory, *directory.parents):
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise PublishError("Package directory has an unsafe ancestor")
        manifest_raw = _plain_bytes(directory / "release-manifest.json", MAX_JSON_BYTES)
        manifest = json.loads(manifest_raw)
        if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int \
                or manifest["schema_version"] != 1 \
                or manifest.get("source_sha") != revision or manifest.get("version") != version:
            raise PublishError("Package manifest identity mismatch")
        names = {f"flightboard-skill-{version}.zip", f"flightboard-plugin-{version}.zip"}
        assets = manifest.get("assets")
        if not isinstance(assets, list) or len(assets) != 2 \
                or any(not isinstance(entry, dict) for entry in assets) \
                or {entry.get("name") for entry in assets} != names:
            raise PublishError("Package manifest must name the two expected archives")
        found = {}
        for entry in assets:
            name = entry["name"]
            raw = _plain_bytes(directory / name, MAX_ASSET_BYTES)
            digest = hashlib.sha256(raw).hexdigest()
            if type(entry.get("size")) is not int or entry["size"] != len(raw) or entry.get("sha256") != digest:
                raise PublishError("Package archive checksum mismatch")
            found[name] = {"path": directory / name, "size": len(raw), "sha256": digest}
        found["release-manifest.json"] = {"path": directory / "release-manifest.json", "size": len(manifest_raw),
                                          "sha256": hashlib.sha256(manifest_raw).hexdigest()}
        sums = _plain_bytes(directory / "SHA256SUMS", 4096)
        expected = {entry["sha256"] + "  " + name for name, entry in found.items()}
        if set(sums.decode("ascii").splitlines()) != expected or len(sums.decode("ascii").splitlines()) != 3:
            raise PublishError("SHA256SUMS does not match the exact archives and manifest")
        found["SHA256SUMS"] = {"path": directory / "SHA256SUMS", "size": len(sums),
                                "sha256": hashlib.sha256(sums).hexdigest()}
        return dict(sorted(found.items()))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, PublishError):
            raise
        raise PublishError("Invalid local release packages") from exc


def _commit(reference: object) -> str:
    if not isinstance(reference, dict) or not isinstance(reference.get("object"), dict):
        raise PublishError("Invalid GitHub reference")
    value = reference["object"]
    if value.get("type") != "commit" or not isinstance(value.get("sha"), str) \
            or SHA.fullmatch(value["sha"]) is None:
        raise PublishError("GitHub reference is not a direct full commit")
    return value["sha"]


def _remote_assets(release: object, expected: dict[str, dict], *, complete: bool) -> set[str]:
    if not isinstance(release, dict) or type(release.get("draft")) is not bool \
            or release.get("prerelease") is not False or not isinstance(release.get("assets"), list):
        raise PublishError("Invalid release metadata")
    seen = set()
    for asset in release["assets"]:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise PublishError("Invalid release asset")
        name = asset["name"]
        if name in seen or name not in expected:
            raise PublishError("Unexpected or duplicate release asset; nothing will be overwritten")
        wanted = expected[name]
        if asset.get("state") != "uploaded" or type(asset.get("size")) is not int \
                or asset["size"] != wanted["size"] or asset.get("digest") != "sha256:" + wanted["sha256"]:
            raise PublishError("Published asset identity mismatch; nothing will be overwritten")
        seen.add(name)
    if complete and seen != set(expected):
        raise PublishError("Published release has missing assets")
    return seen


def _resumable_assets(release: dict, expected: dict[str, dict], tag: str, revision: str) -> tuple[set[str], list[int]]:
    """Validate a matching draft completely before identifying empty failed uploads."""
    if release.get("tag_name") != tag or release.get("target_commitish") != revision:
        raise PublishError("Existing draft targets another tag or revision")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise PublishError("Invalid release metadata")
    names, retained, failed = set(), [], []
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise PublishError("Invalid release asset")
        name = asset["name"]
        if name in names or name not in expected:
            raise PublishError("Unexpected or duplicate release asset; nothing will be overwritten")
        names.add(name)
        if asset.get("state") != "starter":
            retained.append(asset)
            continue
        identity = asset.get("id")
        if type(asset.get("size")) is not int or asset["size"] != 0 \
                or type(identity) is not int or identity <= 0 \
                or sum(isinstance(other, dict) and other.get("id") == identity for other in assets) != 1:
            raise PublishError("Failed upload is not confirmed empty and unambiguous")
        failed.append(identity)
    present = _remote_assets({**release, "assets": retained}, expected, complete=False)
    return present, failed


def _release(gh, endpoint: str, repository: str, tag: str, *, optional=False):
    found = gh.get(endpoint + "/releases/tags/" + tag, optional=True)
    if found is not None:
        return found
    identity = gh.pending_release_id(repository, tag)
    if identity is not None:
        return gh.get(endpoint + "/releases/" + str(identity))
    if optional:
        return None
    raise PublishError("Expected release was not found")


def publish(directory: Path, version: str, revision: str, repository: str, *, gh=None) -> dict:
    expected = packages(directory, version, revision)
    if REPOSITORY.fullmatch(repository) is None or ".." in repository or repository.endswith("."):
        raise PublishError("Expected a plain GitHub owner/repository")
    gh = Gh() if gh is None else gh
    tag, endpoint = "v" + version, "repos/" + repository
    repo_argument = "github.com/" + repository
    tag_ref = gh.get(endpoint + "/git/ref/tags/" + tag, optional=True)
    if tag_ref is not None and _commit(tag_ref) != revision:
        raise PublishError("Existing release tag points to another commit")
    release = _release(gh, endpoint, repository, tag, optional=True)
    if release is not None:
        if isinstance(release, dict) and release.get("draft") is True:
            present, failed = _resumable_assets(release, expected, tag, revision)
            for identity in failed:
                gh.run("api", "--hostname", "github.com", "--method", "DELETE",
                       endpoint + "/releases/assets/" + str(identity))
        else:
            present = _remote_assets(release, expected, complete=True)
            if tag_ref is None:
                raise PublishError("Published release has no matching tag")
            return {"status": "already_published", "tag": tag, "source_sha": revision, "assets": len(present)}
    else:
        present = set()
        with tempfile.TemporaryDirectory(prefix="flightboard-release-notes-") as temporary:
            notes = Path(temporary) / "notes.md"
            notes.write_text(
                f"Flightboard {version}\n\nSource commit: `{revision}`.\n\n"
                "Download the skill archive for the standalone user skill, or the plugin archive for local "
                "plugin installation. Verify SHA256SUMS before extracting. "
                f"[Installation and updates](https://github.com/{repository}/blob/{revision}/docs/releases.md). "
                "This release does not restart existing dashboards.\n",
                encoding="utf-8", newline="\n")
            gh.run("release", "create", tag, "--repo", repo_argument, "--target", revision, "--draft",
                   "--title", "Flightboard " + version, "--notes-file", str(notes))
    missing = [str(entry["path"]) for name, entry in expected.items() if name not in present]
    if missing:
        gh.run("release", "upload", tag, *missing, "--repo", repo_argument)
    release = _release(gh, endpoint, repository, tag)
    _remote_assets(release, expected, complete=True)
    if not release["draft"] or release.get("target_commitish") != revision:
        raise PublishError("Release changed during publication")
    tag_ref = gh.get(endpoint + "/git/ref/tags/" + tag, optional=True)
    if tag_ref is not None and _commit(tag_ref) != revision:
        raise PublishError("Release tag changed during publication")
    current_main = _commit(gh.get(endpoint + "/git/ref/heads/main"))
    latest = current_main == revision
    gh.run("release", "edit", tag, "--repo", repo_argument, "--draft=false",
           "--latest=" + str(latest).lower())
    if _commit(gh.get(endpoint + "/git/ref/tags/" + tag)) != revision:
        raise PublishError("Final release tag does not match the validated commit")
    final = _release(gh, endpoint, repository, tag)
    _remote_assets(final, expected, complete=True)
    if final["draft"]:
        raise PublishError("Release remains a draft")
    return {"status": "published", "tag": tag, "source_sha": revision, "assets": len(expected), "latest": latest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--repo", required=True)
    arguments = parser.parse_args()
    try:
        result = publish(arguments.directory, arguments.version, arguments.ref, arguments.repo)
    except PublishError as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
