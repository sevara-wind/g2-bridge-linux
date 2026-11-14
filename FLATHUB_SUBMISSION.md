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

## Draft PR description / permission justifications (adapt as needed)

**Summary**
- App: G2 Bridge (`io.github.sevara_wind.G2Bridge`)
- Function: Streams a GNU/Linux desktop to DJI Goggles 2 / Integra over USB (Virtual Flight mode, stock firmware) using a `kmsgrab`-based low-latency pipeline and GTK UI.
- Primarily tested on: Steam Deck with Bazzite OS.

**Permissions (justify in PR)**
- `--device=all` and `/run/udev:ro`: required for USB access to DJI goggles and DRM/KMS capture devices used by the streaming pipeline.
- `--filesystem=xdg-run/pipewire-0`: required for portal/PipeWire-related capture paths where applicable.
- `--talk-name=org.freedesktop.portal.Desktop`: screen capture/portal integration.
- `--talk-name=org.freedesktop.Flatpak` and `flatpak-spawn --host`: current implementation launches the capture/stream helper on the host to access host `ffmpeg`/DRM/USB and to run privileged operations required for `kmsgrab`.
- `--talk-name=org.gnome.ScreenSaver`, `--talk-name=org.gnome.Mutter.DisplayConfig`, `--talk-name=org.kde.kglobalaccel`, `--talk-name=org.kde.Solid.PowerManagement`: display/power related behavior (e.g. preventing interruptions / screen handling where supported).
- `xdg-data/config/cache/g2-bridge:create`: runtime state, logs, and bundled runtime deployment.

**Known limitations / reviewer notes**
- The app is not fully sandbox-compatible for `kmsgrab`: it depends on host `python3`, host `ffmpeg` (with `kmsgrab`), host DRM/USB access, and may invoke `pkexec`. This should be clearly disclosed and may require redesign or strong justification for Flathub acceptance.
- Hardware/OS/compositor dependent; primarily tested on Steam Deck with Bazzite OS.
