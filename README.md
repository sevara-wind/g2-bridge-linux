# G2 Bridge

> Based on [Ammaar-Alam/g2-bridge](https://github.com/Ammaar-Alam/g2-bridge) by Ammaar Alam, with additional Linux/Bazzite/Steam Deck adaptations (kmsgrab/Flatpak/Decky), UI changes, and local fixes.

![G2 Bridge on GNU/Linux](docs/images/app-screenshot.png)

Stream your Windows or Mac desktop to DJI Goggles 2 or DJI Goggles Integra over USB. The goggles use Virtual Flight mode with stock firmware. The simulator and controller run on the computer.

The bridge detects the model when it connects:

| Goggles | Identity | Tested firmware |
| --- | --- | --- |
| DJI Goggles 2 | `E3T ZV900` | 01.11.00.00, 01.14.00.00 |
| DJI Goggles Integra | `E3T ZV901` | 01.09.00.00 |

We measured **about 12 ms median monitor-to-lens delay** at 1080p100. See [how we measured it](docs/LATENCY.md).

## Requirements

On Windows, you need the following hardware and software:

- 64-bit Windows and Python 3.10 or later.
- An NVIDIA GPU with NVENC support.
- FFmpeg with `gfxcapture` and `h264_nvenc`. To install it, run `winget install Gyan.FFmpeg`.
- [DJI Assistant 2 (Consumer Drones Series)](https://www.dji.com/downloads/softwares/dji-assistant-2-consumer-drones-series), which installs the DJI USB driver 5.0.0.7. See [USB and driver requirements](docs/PROTOCOL.md#usb-and-session).

Tests used FFmpeg build `2026-11-05-git-0893feba65` and NVIDIA driver 610.74.

On macOS, you need the following:

- macOS and Python 3.10 or later.
- Apple's command-line developer tools, which build the screen capture helper on the first run.
- [Homebrew](https://brew.sh), for libusb. Before macOS 12.3, the bridge also needs FFmpeg.
- A USB-A-to-USB-C cable. If the Mac has only USB-C ports, add a USB-C-to-USB-A adapter. Over a USB-C-to-USB-C cable, the goggles take the USB host role and the Mac can't detect them.

The stream script offers to install whatever is missing. Tests used an M2 Pro MacBook Pro with macOS 27.0, Swift 6.4.2, and Homebrew FFmpeg 8.1.1.

## Start streaming

1. Power on the goggles, connect a USB data cable, and open **More > DJI Virtual Flight**. On a Mac, when macOS asks whether the accessory can connect, select **Allow**.
2. From the repository root, install the Python dependencies.

   On Windows, run:

   ```powershell
   python -m pip install -r requirements.txt
   ```

   On macOS, run:

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```

3. Start the stream.

   On Windows, run:

   ```powershell
   python scripts/stream_desktop.py
   ```

   On macOS, run:

   ```bash
   .venv/bin/python scripts/stream_desktop.py
   ```

   On Windows, the script finds the DJI driver and FFmpeg automatically. If either is installed somewhere else, pass `--dll` or `--ffmpeg` with the file path.

   On a Mac, the script offers to install anything that's missing, and it builds the screen capture helper on the first run. If the screen can't be captured, go to **System Settings > Privacy & Security** and allow screen recording for your terminal.

The default output is **1920x1080** at a **100 fps encoder target**. Windows uses **32 Mbps**, or automatically selects **24 Mbps at 60 fps** and **30 Mbps at 75 fps**. macOS uses **20 Mbps**. To stop streaming, press **Ctrl+C**. The bridge writes logs to `work/logs/`.

Use these options to adjust the stream:

| Option | Values |
| --- | --- |
| `--fps` | `60`, `75`, `90`, `100` |
| `--bitrate-mbps` | `8`, `10`, `12`, `16`, `20`, `24`. On Windows, also `30`, `32`, and `40` |
| `--display` | Monitor index, starting at `0` |
| `--capture` | Windows: `gfxcapture` or `ddagrab`. macOS: `screencapturekit` or `avfoundation` |

Run `python scripts/stream_desktop.py --help` for all options.

For example, use `python scripts/stream_desktop.py --fps 90` to target 90 fps.
These values set the stream rate, not the goggles' panel refresh rate. Lower
rates provide more bits per frame at the same bitrate, but increase the time
between frames. The 100 fps target has the shortest frame interval.

Windows encoding uses gradual refresh to reduce periodic compression blur.
For details, see the [quality measurements and reproduction steps](docs/research/WINDOWS_QUALITY.md).

## GNU/Linux adaptation (Steam Deck / Bazzite)

This repository includes a GNU/Linux adaptation focused on low-latency streaming to DJI Goggles 2 / Integra over USB (Virtual Flight mode, stock firmware), with a GTK interface and Flatpak packaging.

![G2 Bridge on GNU/Linux](docs/images/app-screenshot.png)

### Functionality
- **Desktop streaming via `kmsgrab`** (KMS/DRM capture) encoded with `libx264` for a low-latency PC route.
- **Configurable stream settings:** rotation, FPS, bitrate, keyframe interval, and x264 preset.
- **Optional "Dim device screen"** mode to dim the device display while streaming and restore brightness on stop.
- **GTK UI:** start/stop streaming, view logs, open log/GitHub links, and manage settings.
- **Flatpak packaging:** manifests and metadata for local builds and Flathub-oriented submission (`flatpak/io.github.sevara_wind.G2Bridge.*`).

### CLI (Linux capture paths)
`scripts/stream_linux.py` reuses the same session, handshake and packetizer with Linux capture paths:

- **portal ScreenCast** through GStreamer/PipeWire (GNOME Wayland; no root);
- FFmpeg + VAAPI/libx264 for a test pattern, a video file, a V4L2 device or `kmsgrab`.

```bash
./setup_bazzite.sh
.venv/bin/python scripts/stream_linux.py --source desktop   # portal
.venv/bin/python scripts/stream_linux.py --source testsrc
.venv/bin/python scripts/stream_linux.py --source kmsgrab --kmsgrab-rotate 270 --encoder libx264 --preset ultrafast --fps 100 --bitrate-mbps 40 --keyframe-seconds 3
```

See [README_BAZZITE.md](README_BAZZITE.md) for Bazzite/Steam Deck installation, cable/host-mode notes, and troubleshooting. For Flatpak details see [`flatpak/README.md`](flatpak/README.md).

## Run tests

Run the tests from the repository root:

```powershell
python -m unittest discover -s tests -v
```

See the [video-delay measurement guide](docs/LATENCY.md), [PC protocol](docs/PROTOCOL.md), and [reverse-engineering data and tools](docs/research/README.md).

## Contributing

See the [contribution guide](CONTRIBUTING.md) to report bugs, submit changes, or share protocol research.

## License

Copyright (C) 2026 G2 Bridge contributors.

The original code and documentation are licensed under the [GNU General Public License v3.0 only](LICENSE) (`GPL-3.0-only`). Third-party materials retain their own licenses.
