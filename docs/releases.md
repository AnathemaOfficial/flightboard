<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Installable releases

[GitHub Releases](https://github.com/AnathemaOfficial/flightboard/releases) provides
the portable skill archive, the plugin archive, a release manifest and SHA-256
checksums. Python 3.12+ and Git 2.41+ are still the runtime requirements. The
optional GitHub observer additionally uses an existing `gh` CLI login.

## Choose an archive

- `flightboard-skill-VERSION.zip`: the standalone skill for Codex or another host
  supporting `SKILL.md`. Extract it outside an observed project, then copy its
  `flightboard` directory into the host's user skill directory. For Codex this is
  normally `~/.agents/skills/flightboard`.
- `flightboard-plugin-VERSION.zip`: the complete portable plugin layout for the
  existing local-marketplace/plugin installation commands in the main README.
  Extract it to a dedicated directory and use that directory as the local source.

Download `SHA256SUMS` and `release-manifest.json` from the same release. Verify the
archive before extracting it. In PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 .\flightboard-skill-VERSION.zip
Get-Content .\SHA256SUMS
```

On Linux, run `sha256sum flightboard-skill-VERSION.zip`; on macOS, run
`shasum -a 256 flightboard-skill-VERSION.zip`. Compare the selected archive's name
and full digest with its line in `SHA256SUMS`. A full `sha256sum -c SHA256SUMS`
check requires both archives and the manifest to be downloaded together.
The checksums detect accidental
corruption; they are not an independent signature of the release publisher.

Before replacing an existing skill, retain its current directory as a backup.
Preserve any separate startup configuration. Installing an archive does not update
an already-running process or the Windows startup helper's copied engine. Use the
existing startup update procedure deliberately and restart only the dashboards
you intend to update. Plugin hosts manage their own plugin cache; use their update
commands rather than editing that cache manually.

After installation, verify the installed engine:

```text
python -I -B PATH-TO-SKILL/scripts/flightboard.py --version
```

The printed version must match the selected release manifest. A changed page
template needs one browser reload; subsequent data refreshes remain automatic.

## Publication policy

Every update to `main` that passes all platform tests, strict plugin validation,
licensing and package checks produces an immutable release with installation
archives. Failed validation produces no stable release. PR runs build preview
archives without release-write permissions. A separately published PR preview is
marked as a prerelease and does not become the latest stable release.

The source manifests and runtime keep a base version such as `0.2.0`. Stable
distribution versions use the same major/minor and the CI run number as the patch,
for example `0.2.123`. PR runs also consume CI run numbers, so gaps are normal.
Only the packaged runtime version and the two plugin versions are stamped; no
automatic version commit is added to the repository. The manifest records the
base version, distribution version, exact source commit and asset digests.

A preview uses a version such as `0.2.0-rc.5.g0123456789ab`. The source commit, not
a mutable branch name, identifies its contents. Repeating a release verifies the
existing tag and asset bytes instead of replacing them. Older runs must not move
the latest-release pointer backwards.

The release workflow becomes active when its PR is merged into `main`. Creating
or reviewing that PR does not itself authorize a merge.
