<!-- Copyright 2026 A.S.D - Alexander Schwartz Developments. SPDX-License-Identifier: Apache-2.0 -->
# proxtool as a VesperApp add-on

**Goal:** VesperApp users get ProxTit Tags the way they get VesperApp's other
optional parts: from the **Plugins** tab, installed and updated in one click. There
is no other link between the two programs: proxtool runs as its own window,
VesperApp only distributes, installs, updates and starts it. The open-source
route (GitHub releases, `pip`) stays.

**Status:** proxtool side done (this repository builds the pack). VesperApp side
**not done**: it needs the small change described below, in VesperAppCode.

## What proxtool provides

A release tag `vX.Y.Z` (`.github/workflows/release.yml`) builds, per platform
(`win-x64`, `linux-x64`):

| Asset | Content |
|---|---|
| `proxtool-X.Y.Z-<rid>.zip` | the stand-alone programs (PyInstaller): `ProxTitTags` (window), `proxtool` (command line), their runtime, licence and notices |
| `proxtool-plugin-X.Y.Z-<rid>.zip` | the same files plus `plugin.json`, the VesperApp pack |
| `proxtool-plugin-X.Y.Z-<rid>.json` | the pack's entry for the feed |

All three are attached to the GitHub release. If the repository has the CDN
secrets that VesperApp's other packs use (`AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, variables `AWS_REGION`, `RELEASE_S3_BUCKET`,
`CF_DISTRIBUTION_ID`), the workflow also uploads the packs to
`plugins/proxtool/<version>/` and merges the entries into
`plugins/proxtool/index.json`. That is the same feed format as the GNSS pack
(`docs/ci-templates/gnss-plugin-release.yml` in VesperAppCode). Without the
secrets this step is skipped.

`plugin.json` (VesperApp's `PluginManifest` fields, plus `launch`):

```json
{
  "name": "ProxTit Tags",
  "kind": "tool",
  "version": "0.3.0",
  "abi": 0,
  "platform": "win-x64",
  "entryDll": null,
  "launch": "ProxTitTags.exe",
  "commandLine": "proxtool.exe",
  "description": "Download, clock, settings and firmware update of ProxTit Bluetooth tags.",
  "homepage": "https://github.com/ASD-Alexander-Schwartz-Developments/proxtool",
  "license": "Apache-2.0"
}
```

Feed entry (VesperApp's `ReleaseEntry`, plus `kind`):
`{"version", "name", "target", "asset", "size", "sha256", "abi": 0, "kind": "tool"}`.

## What VesperApp needs (proposal, not implemented)

Today a pack must carry a .NET adapter DLL built against the plugin ABI;
`PluginUpdateService.IsInstallable` and `ManifestProblem` reject anything else.
That is right for packs that VesperApp *loads*. A **tool** pack is never loaded,
only installed and started, so:

1. **`PluginManifest`**: add `string? Launch` (the executable, relative to the
   pack folder) and treat `Kind == "tool"` as a tool pack.
2. **`ReleaseEntry`**: add `string? Kind`.
3. **`PluginUpdateService`**:
   - `IsInstallable`: a tool entry (`Kind == "tool"`) needs an asset and a
     matching target. **No ABI check**: the ABI describes the .NET contracts, which
     a tool does not use.
   - `ManifestProblem`: for a tool, check that `Launch` exists instead of
     `EntryDll`.
   - Download, SHA-256 check, staging and `EnsureUnixExecutables` stay as they
     are.
4. **`PluginLoader`**: skip packs whose manifest kind is "tool" (nothing to bind).
5. **Plugins tab**: the tool's card shows **Open** when installed, starting
   `<pack folder>/<Launch>` as a separate process. It is installed and updated
   like any card, but applied at once rather than "on next launch", because
   nothing is loaded into VesperApp. Only an update while ProxTit Tags is running
   must wait until it is closed (the files are in use on Windows).
6. **Catalog**: add a "ProxTit Tags" card bound to the feed `plugins/proxtool/index.json`,
   pack name `proxtool`, no entitlement.

About 60 lines in VesperApp, no change to its plugin ABI. Packs stay in the
per-user plugins folder, so VesperApp's own updates never remove them.

## Notes

- **Size:** about 18 MB per platform (Python runtime, Tk, Bluetooth libraries).
- **Signing:** Windows SmartScreen may warn on an unsigned `ProxTitTags.exe`, as
  for any unsigned download. Code-signing the executables, with ASD's certificate
  in CI, is a later step and applies to VesperApp's packs as well.
- **Licences:** the pack contains `LICENSE`, `NOTICE` and
  `THIRD-PARTY-NOTICES.md` (all permissive; PyInstaller's licence allows packaged
  programs under any licence).
- **Linux:** the pack runs the same way; VesperApp's `EnsureUnixExecutables`
  sets the execute bits after unzipping.
