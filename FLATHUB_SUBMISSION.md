# Flathub submission notes (io.github.sevara_wind.G2Bridge)

This repository includes Flathub-oriented files:
- `flatpak/io.github.sevara_wind.G2Bridge.yml` (manifest, git source pinned to a commit)
- `flatpak/io.github.sevara_wind.G2Bridge.metainfo.xml`
- `flatpak/io.github.sevara_wind.G2Bridge.desktop`
- `flatpak/io.github.sevara_wind.G2Bridge.svg`

## Before submitting
1. Ensure the pinned commit in `flatpak/io.github.sevara_wind.G2Bridge.yml` (`sources[0].commit`) points to the commit on `main` that contains the exact state you want Flathub to build.
2. Validate metadata locally:
   - `appstreamcli validate flatpak/io.github.sevara_wind.G2Bridge.metainfo.xml` (if available)
   - `desktop-file-validate flatpak/io.github.sevara_wind.G2Bridge.desktop` (if available)
3. Test a clean/sandboxed build on a host with Flatpak Builder:
   ```bash
   flatpak run org.flatpak.Builder --user --install --force-clean --sandbox build-dir flatpak/io.github.sevara_wind.G2Bridge.yml
   ```

## Submission flow
- Follow Flathub docs: https://docs.flathub.org/docs/for-app-authors/submission
- New app submissions are made via PR to https://github.com/flathub/flathub (see current Flathub instructions for required repo layout/files).

## Known review blockers / permissions to justify
The current implementation relies on host access for `kmsgrab` capture and privileged operations:
- `--talk-name=org.freedesktop.Flatpak` and runtime use of `flatpak-spawn --host ...` (launcher/app spawn host-side stream)
- `pkexec`/host `python3`/host `ffmpeg` + DRM/USB access expectations
- Broad permissions such as `--device=all`, `/run/udev` access, PipeWire socket access, and extra D-Bus talk names

For Flathub acceptance, expect to either:
- provide strong justification for each permission/host escape and demonstrate necessity, or
- redesign to a sandbox-compatible capture/streaming approach (if feasible).

## Other notes
- Functionality is hardware/OS-dependent (DJI Goggles 2/Integra, USB/DRM, compositor behavior). Primarily tested on Steam Deck with Bazzite OS.
- Keep `releases` in metainfo and screenshot/URLs up to date for each published version.
