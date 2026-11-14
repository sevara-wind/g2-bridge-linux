# Flatpak: g2-bridge

The Flatpak runs the **portal ScreenCast** path:

- xdg-desktop-portal asks for the monitor and composites the mouse cursor;
- `pipewiresrc` reads the consented stream;
- `x264enc` (or `vaapih264enc`) and `avimux` write AVI to stdout;
- the existing `BridgeEngine` sends H.264 over USB.

It does **not** need root, `kmsgrab`, or an FFmpeg build with PipeWire input.
`--device=all` is used for the goggles' USB device.

## Build

On the host (not inside the OpenCode sandbox):

```bash
flatpak install flathub org.gnome.Platform//49 org.gnome.Sdk//49
flatpak-builder --user --install --force-clean build-dir \
    flatpak/io.github.sevara.G2Bridge.yml
```

If `flatpak-builder` is missing on Bazzite:

```bash
sudo rpm-ostree install flatpak-builder
sudo systemctl reboot
```

Run:

```bash
flatpak run io.github.sevara.G2Bridge
```

The first run shows a rotation picker (if `zenity`/`kdialog` is available),
then opens the GNOME screen-sharing dialog. Choose the Deck's monitor.

Default stream settings: **100 fps, 12 Mbps** (portal path). All screen
rotations are available:

```bash
flatpak run io.github.sevara.G2Bridge --portal-rotate none
flatpak run io.github.sevara.G2Bridge --portal-rotate 90
flatpak run io.github.sevara.G2Bridge --portal-rotate 180
flatpak run io.github.sevara.G2Bridge --portal-rotate 270
```

Or set `G2_PORTAL_ROTATE` (none, 90, 180, 270):

```bash
flatpak run --env=G2_PORTAL_ROTATE=270 io.github.sevara.G2Bridge
```

Arguments are passed through, so the diagnostic and non-desktop paths still
work while the Flatpak runtime provides the binaries:

```bash
flatpak run io.github.sevara.G2Bridge --print-command
flatpak run io.github.sevara.G2Bridge --check
flatpak run io.github.sevara.G2Bridge --source testsrc
```

The testsrc/v4l2 paths call FFmpeg, which may not be in the GNOME runtime.
The portal path is the supported Flatpak path. If you need analog capture in
the Flatpak, add an FFmpeg module to the manifest.

## What is inside

- Python code from `goggles_bridge/` and `scripts/stream_linux.py`;
- vendored `jeepney` for the portal D-Bus calls;
- vendored PyUSB wheel for the goggles;
- a terminal launcher and desktop entry.

The runtime supplies Python 3, GStreamer, PipeWire and the portal proxy. The
launcher adds the vendored modules to `PYTHONPATH`; no `pip install` happens at
runtime.
