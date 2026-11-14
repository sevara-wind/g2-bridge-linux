#!/usr/bin/env bash
# Prepare g2-bridge for Steam Deck / Bazzite (Fedora Atomic).
# Run this on the HOST (Konsole), not inside a Flatpak sandbox.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

say "== g2-bridge: Bazzite / Steam Deck setup =="
say ""

command -v python3 >/dev/null 2>&1 || die "python3 not found."
python3 - <<'PY' || die "Python 3.10 or newer is required."
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"Python {sys.version.split()[0]} is too old")
PY

if ! command -v ffmpeg >/dev/null 2>&1; then
    say "WARNING: ffmpeg not found."
    say "  testsrc/v4l2/file/kmsgrab need it: sudo rpm-ostree install ffmpeg && reboot"
    say "  The recommended portal desktop path does not need ffmpeg."
fi

# A .venv copied from another machine, a Flatpak, or an older Python minor
# version may point at a different site-packages directory. Verify that both
# the interpreter and PyUSB actually import, then recreate it if they do not.
if [ -d .venv ] && ! .venv/bin/python -c 'import sys, usb' >/dev/null 2>&1; then
    say "Removing unusable .venv (interpreter or PyUSB mismatch)"
    rm -rf .venv
fi

if [ ! -x .venv/bin/python ]; then
    say "Creating .venv"
    if ! python3 -m venv .venv; then
        rm -rf .venv
        die "python3 -m venv failed (ensurepip is missing). Install uv:
  curl -LsSf https://astral.sh/uv/install.sh | sh
then:
  uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt"
    fi
fi

if [ -x .venv/bin/pip ] && .venv/bin/pip --version >/dev/null 2>&1; then
    if [ -f vendor/pyusb-1.3.1-py3-none-any.whl ]; then
        say "Installing PyUSB from the vendored wheel (offline)"
        .venv/bin/pip install --no-index --find-links vendor 'PyUSB==1.3.1'
    else
        .venv/bin/pip install -r requirements.txt
    fi
elif command -v uv >/dev/null 2>&1; then
    say "No pip inside .venv; using uv"
    uv pip install --python .venv/bin/python -r requirements.txt
else
    die "No pip inside .venv and uv is not installed. Run:
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ./setup_bazzite.sh"
fi

.venv/bin/python - <<'PY'
import usb
print("PyUSB", getattr(usb, "__version__", "ok"))
PY

say ""
say "FFmpeg encoders:"
ffmpeg -hide_banner -encoders 2>/dev/null | grep -E 'h264_vaapi|libx264' || \
    say "  WARNING: neither h264_vaapi nor libx264 found. Install a full FFmpeg build."

if [ -e /dev/dri/renderD128 ]; then
    say "VAAPI device: /dev/dri/renderD128 (ok)"
else
    say "VAAPI device missing: use --encoder libx264 (more CPU)."
fi

say ""
say "Desktop portal (recommended, includes the cursor):"
if command -v gst-launch-1.0 >/dev/null 2>&1; then
    say "  gst-launch-1.0: ok"
else
    say "  WARNING: gst-launch-1.0 missing. Install GStreamer tools."
fi
for element in pipewiresrc x264enc vaapih264enc; do
    if command -v gst-inspect-1.0 >/dev/null 2>&1 && \
            gst-inspect-1.0 "$element" >/dev/null 2>&1; then
        say "  $element: ok"
    else
        say "  $element: missing"
    fi
done
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
    say "  WARNING: DBUS_SESSION_BUS_ADDRESS is empty; the portal needs a desktop session."
fi

say ""
say "Install the udev rule once:"
say "  sudo cp scripts/linux/60-dji-goggles.rules /etc/udev/rules.d/"
say "  sudo udevadm control --reload && sudo udevadm trigger"

if ! getent group plugdev >/dev/null 2>&1; then
    say ""
    say "Note: group 'plugdev' does not exist on Fedora. If you get 'Access denied':"
    say "  sudo groupadd -r plugdev && sudo usermod -aG plugdev \"$USER\"   # then re-login"
    say "  or run the first probe with sudo."
fi

say ""
say "Check that the goggles are visible (More > DJI Virtual Flight must be open):"
say "  lsusb | grep 2ca3"
say ""
say "Probe:"
say "  .venv/bin/python tools/research/probe_goggles.py --descriptors-only"
say "  .venv/bin/python tools/research/probe_goggles.py"
say "  .venv/bin/python tools/research/probe_goggles.py --simulator"
say ""
say "First video (moving test pattern):"
say "  .venv/bin/python scripts/stream_linux.py --source testsrc"
say ""
say "Desktop (Wayland portal, includes the cursor, no root):"
say "  .venv/bin/python scripts/stream_linux.py --source desktop"
say ""
say "kmsgrab fallback (needs root):"
say "  sudo .venv/bin/python scripts/stream_linux.py --source desktop \\"
say "      --desktop-capture kmsgrab --kmsgrab-rotate 270 --bitrate-mbps 14"
say ""
say "Local video file (looped):"
say "  .venv/bin/python scripts/stream_linux.py --source file --file ~/Videos/clip.mp4"
say ""
say "Flatpak (portal path, no root):"
say "  flatpak-builder --user --install --force-clean build-dir flatpak/io.github.sevara.G2Bridge.yml"
say "  flatpak run io.github.sevara.G2Bridge"
say ""
say "See README_BAZZITE.md and flatpak/README.md for details and troubleshooting."
