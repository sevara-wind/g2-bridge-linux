#!/usr/bin/env python3
"""Stream video INTO DJI Goggles 2 / Integra on GNU/Linux.

The upstream g2-bridge ships capture paths for Windows and macOS only. This
script reuses its USB session, handshake and packetizer, and supplies a Linux
capture path (FFmpeg/VAAPI/libx264 for a test pattern, file, V4L2 device or
kmsgrab; GStreamer/pipewiresrc/x264enc for the GNOME portal). Goggles must be in
More > DJI Virtual Flight with stock firmware.

Examples:
    # prove the video path with a moving test pattern (no camera needed)
    .venv/bin/python scripts/stream_linux.py --source testsrc

    # analog camera / receiver through a USB capture stick
    .venv/bin/python scripts/stream_linux.py --source v4l2 --device /dev/video0 \
        --input-size 720x576 --input-fps 25 --fps 60 --bitrate-mbps 10

    # a local video file, looped
    .venv/bin/python scripts/stream_linux.py --source file --file clip.mp4

    # Linux desktop (portal includes the mouse cursor and needs no root)
    .venv/bin/python scripts/stream_linux.py --source desktop --desktop-capture portal
    # fallback for a compositor without a ScreenCast portal
    sudo .venv/bin/python scripts/stream_linux.py --source desktop --desktop-capture kmsgrab

    # only print the capture command / test the encoder without goggles
    .venv/bin/python scripts/stream_linux.py --source testsrc --print-command
    .venv/bin/python scripts/stream_linux.py --source testsrc --check
"""
import argparse
from functools import lru_cache
import os
from datetime import datetime
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from goggles_bridge import engine  # noqa: E402
from goggles_bridge.engine import (  # noqa: E402
    HEIGHT, MAX_FRAME_BYTES, WIDTH, BridgeEngine, BridgeSettings,
)


BITRATES = (8, 10, 12, 14, 16, 18, 20, 24, 30, 32, 40)
SCALERS = ('fast_bilinear', 'bilinear', 'bicubic', 'lanczos')

# kmsgrab exposes the scanout framebuffer's DRM fourcc; hwdownload can only
# emit that exact software format. Values are the hex fourcc printed by
# "Template framebuffer is ..." and map to kmsgrab's own pixfmt table.
DRM_FORMAT_TO_PIXFMT = {
    '34325258': 'bgr0',       # XRGB8888 (XR24)
    '34325241': 'bgra',       # ARGB8888 (AR24)
    '34324258': 'rgb0',       # XBGR8888 (XB24)
    '34324241': 'rgba',       # ABGR8888 (AB24)
    '30335258': 'x2rgb10le',  # XRGB2101010 (XR30, Steam Deck)
    '3231564e': 'nv12',       # NV12
    '56595559': 'yuyv422',    # YUYV
}


def run_ffmpeg_capability(ffmpeg, flag):
    try:
        row = subprocess.run([str(ffmpeg), '-hide_banner', flag], capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return (row.stdout or '') + (row.stderr or '')


def probe_kmsgrab_format(ffmpeg, device):
    """Ask kmsgrab which software pixel format the active scanout has."""
    cmd = [str(ffmpeg), '-hide_banner', '-nostdin', '-loglevel', 'verbose',
           '-f', 'kmsgrab', '-device', str(device), '-framerate', '1',
           '-i', '-', '-frames:v', '0', '-f', 'null', '-']
    try:
        row = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (row.stderr or '') + '\n' + (row.stdout or '')
    match = re.search(r'Format is ([a-zA-Z0-9_]+), from DRM format', output)
    if match:
        return match.group(1)
    match = re.search(r'Template framebuffer is \d+: \d+x\d+ format ([0-9a-fA-F]+)', output)
    if match:
        return DRM_FORMAT_TO_PIXFMT.get(match.group(1).lower())
    return None


def pick_encoder(args):
    available = run_ffmpeg_capability(args.ffmpeg, '-encoders')
    if args.encoder == 'auto':
        if (args.vaapi_device and Path(args.vaapi_device).exists()
                and 'h264_vaapi' in available):
            return 'vaapi'
        if 'h264_vulkan' in available:
            return 'vulkan'
        if 'libx264' in available:
            return 'libx264'
        raise SystemExit('FFmpeg has neither h264_vaapi, h264_vulkan nor libx264. Install a full FFmpeg build.')
    if args.encoder == 'vaapi':
        if 'h264_vaapi' not in available:
            raise SystemExit('This FFmpeg has no h264_vaapi encoder.')
        if not Path(args.vaapi_device).exists():
            raise SystemExit(f'VAAPI device not found: {args.vaapi_device}')
    elif args.encoder == 'vulkan':
        if 'h264_vulkan' not in available:
            raise SystemExit('This FFmpeg has no h264_vulkan encoder.')
    elif args.encoder == 'libx264':
        if 'libx264' not in available:
            raise SystemExit('This FFmpeg has no libx264 encoder.')
    return args.encoder


@lru_cache(maxsize=None)
def has_filter(ffmpeg, name):
    return name in run_ffmpeg_capability(ffmpeg, '-bsfs')


def video_filter(encoder, desktop_capture=None, kmsgrab_rotate='none',
                 kmsgrab_format='x2rgb10le', kmsgrab_vaapi_map=False,
                 gpu_filters=False, scaler='bicubic'):
    # kmsgrab hands over DRM frames in the scanout format (the Deck uses
    # 10-bit XR30). hwdownload must be told the exact native format; the
    # filter graph otherwise negotiates monow and fails.
    if desktop_capture == 'kmsgrab' and gpu_filters and encoder == 'vaapi':
        # Keep the whole path on the GPU: VAAPI imports the DCC/tiled scanout,
        # converts to NV12, rotates, scales and pads, then the encoder consumes
        # the surface directly. No per-frame readback means the lowest latency.
        chain = 'hwmap=derive_device=vaapi,scale_vaapi=format=nv12,'
        if kmsgrab_rotate == '90':
            chain += 'transpose_vaapi=dir=clock,'
        elif kmsgrab_rotate == '180':
            chain += 'transpose_vaapi=dir=reversal,'
        elif kmsgrab_rotate == '270':
            chain += 'transpose_vaapi=dir=cclock,'
        chain += (f'scale_vaapi=w={WIDTH}:h={HEIGHT}:force_original_aspect_ratio=decrease:'
                  f'force_divisible_by=2,'
                  f'pad_vaapi=w={WIDTH}:h={HEIGHT}:x=(ow-iw)/2:y=(oh-ih)/2')
        return chain

    chain = ''
    if desktop_capture == 'kmsgrab':
        if kmsgrab_vaapi_map:
            # The Deck scanout uses AMD DCC/tiling. Mapping DRM -> VAAPI
            # first lets the driver decompress/detile; a direct hwdownload
            # would copy the compressed buffer as if it were linear. This is
            # needed even when the final encoder is software (libx264).
            chain += 'hwmap=derive_device=vaapi,'
        chain += f'hwdownload,format={kmsgrab_format},'
        if kmsgrab_rotate == '90':
            chain += 'transpose=1,'
        elif kmsgrab_rotate == '180':
            chain += 'hflip,vflip,'
        elif kmsgrab_rotate == '270':
            chain += 'transpose=2,'
    chain += (f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:flags={scaler},'
              f'pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=nv12')
    if encoder == 'vaapi':
        chain += ',hwupload'
    elif encoder == 'vulkan':
        chain += ',hwupload,format=vulkan'
    return chain


def build_command(args, encoder, frames=0, gpu_filters=None):
    fps = args.fps
    bitrate = args.bitrate_mbps * 1_000_000
    vbv = min(bitrate * 2 // fps, MAX_FRAME_BYTES * 8)
    if gpu_filters is None:
        gpu_filters = args.gpu_filters == 'on'
    cmd = [str(args.ffmpeg), '-hide_banner', '-nostdin',
           '-loglevel', 'info' if args.verbose else 'warning']

    if args.source == 'v4l2':
        cmd += ['-f', 'v4l2']
        if args.input_format:
            cmd += ['-input_format', args.input_format]
        if args.input_size:
            cmd += ['-video_size', args.input_size]
        if args.input_fps:
            cmd += ['-framerate', str(args.input_fps)]
        cmd += ['-i', args.device]
    elif args.source == 'file':
        cmd += ['-stream_loop', '-1', '-re', '-i', str(args.file)]
    elif args.source == 'testsrc':
        # -re makes the synthetic source run in real time like a camera would.
        cmd += ['-re', '-f', 'lavfi', '-i', f'testsrc2=size=1280x720:rate={fps}']
    else:  # desktop
        if args.desktop_capture == 'kmsgrab':
            cmd += ['-f', 'kmsgrab', '-device', args.kmsgrab_device,
                    '-framerate', str(args.capture_fps), '-i', '-']
        elif args.desktop_capture == 'pipewire':
            cmd += ['-f', 'pipewire', '-i', str(args.pipewire_node)]
        else:
            display = os.environ.get('DISPLAY') or ':0'
            cmd += ['-f', 'x11grab', '-framerate', str(args.capture_fps),
                    '-draw_mouse', '1', '-i', display]

    if encoder == 'vaapi':
        cmd += ['-vaapi_device', args.vaapi_device]
    elif encoder == 'vulkan':
        cmd += ['-init_hw_device', 'vulkan=vk:0', '-filter_hw_device', 'vk']

    capture_kind = args.desktop_capture if args.source == 'desktop' else None
    rotate = args.kmsgrab_rotate if capture_kind == 'kmsgrab' else 'none'
    cmd += ['-vf', video_filter(encoder, capture_kind, rotate, args.kmsgrab_format,
                                args.kmsgrab_vaapi_map, gpu_filters, args.scaler),
            '-r', str(fps), '-fps_mode', 'cfr', '-an']

    if encoder == 'vaapi':
        cmd += ['-c:v', 'h264_vaapi', '-rc_mode', 'CBR', '-profile:v', 'high',
                '-async_depth', '1', '-max_frame_size', str(MAX_FRAME_BYTES - 1000)]
    elif encoder == 'vulkan':
        cmd += ['-c:v', 'h264_vulkan', '-rc_mode', 'cbr', '-profile:v', 'high',
                '-max_frame_size', str(MAX_FRAME_BYTES - 1000)]
    else:
        x264_params = (
            f'nal-hrd=cbr:scenecut=0:vbv-maxrate={bitrate // 1000}:vbv-bufsize={vbv // 1000}'
        )
        cmd += ['-c:v', 'libx264', '-preset', args.preset, '-tune', 'zerolatency',
                '-profile:v', 'high', '-x264-params', x264_params]

    cmd += ['-b:v', str(bitrate), '-maxrate', str(bitrate), '-bufsize', str(vbv),
            '-bf', '0', '-g', str(fps * args.keyframe_seconds),
            '-level:v', '4.2' if fps == 60 else '5.1',
            '-aud', '1']

    # VAAPI CBR pads short frames with filler-data NALs (type 12). They are
    # useless for the goggles and count against the frame-size limit, so strip
    # them after the encoder. The encoder inserts the AUD itself, which is
    # cheaper and more robust than running h264_metadata over every frame.
    if encoder == 'vaapi' and not args.no_aud_bsf:
        if not has_filter(args.ffmpeg, 'filter_units'):
            raise SystemExit('h264_vaapi CBR needs the filter_units bitstream filter, which this FFmpeg lacks')
        cmd += ['-bsf:v', 'filter_units=remove_types=12']
    elif encoder == 'vulkan' and not args.no_aud_bsf:
        cmd += ['-bsf:v', 'h264_metadata=aud=insert']

    if frames:
        cmd += ['-frames:v', str(frames), '-f', 'null', '-']
    else:
        cmd += ['-flush_packets', '1', '-f', 'avi', 'pipe:1']
    return cmd


def encoder_probe_ok(args, encoder, gpu_filters):
    """Run a two-frame encode to check one capture/filter path."""
    try:
        row = subprocess.run(build_command(args, encoder, frames=2,
                                           gpu_filters=gpu_filters),
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    if args.verbose and row.returncode:
        tail = '\n'.join((row.stderr or '').strip().splitlines()[-4:])
        print(f'Pipeline probe failed:\n{tail}', file=sys.stderr)
    return row.returncode == 0


def resolve_gpu_filters(args, encoder):
    if (args.source != 'desktop' or args.desktop_capture != 'kmsgrab'
            or encoder != 'vaapi' or args.gpu_filters != 'auto'):
        return
    if args.print_command:
        args.gpu_filters = 'on'
        return
    if encoder_probe_ok(args, encoder, True):
        args.gpu_filters = 'on'
        print('Using VAAPI GPU filters (zero-copy, lowest latency)', file=sys.stderr)
    elif encoder_probe_ok(args, encoder, False):
        args.gpu_filters = 'off'
        print('GPU filters unavailable; using VAAPI map + readback', file=sys.stderr)
    else:
        args.gpu_filters = 'on'


def install_linux_encoder(args, encoder):
    def linux_encoder_command(_settings, frames=0):
        return build_command(args, encoder, frames)
    engine.encoder_command = linux_encoder_command


def build_portal_command(args, node, frames=0):
    from goggles_bridge.gst_capture import build_command as build_gst_command
    return build_gst_command(
        node,
        fps=args.fps,
        bitrate_mbps=args.bitrate_mbps,
        rotate=args.portal_rotate,
        encoder=args.portal_encoder,
        frames=frames,
    )


def install_portal_encoder(args, node):
    def portal_encoder_command(_settings, frames=0):
        return build_portal_command(args, node, frames)
    engine.encoder_command = portal_encoder_command


_SCREEN_OFF_DONE = False
_BRIGHTNESS_HOLD_PROC = None
_BRIGHTNESS_SAVED = None

def _brightness_devices():
    devs = []
    try:
        for bl in sorted(Path('/sys/class/backlight').glob('*')):
            b = bl / 'brightness'
            if b.exists():
                devs.append(bl)
    except Exception:
        pass
    return devs


def _start_brightness_blackout():
    global _BRIGHTNESS_HOLD_PROC, _BRIGHTNESS_SAVED
    if _BRIGHTNESS_HOLD_PROC and _BRIGHTNESS_HOLD_PROC.poll() is None:
        return True
    devs = _brightness_devices()
    if not devs:
        return False
    saved = {}
    for bl in devs:
        try:
            saved[str(bl)] = (bl / 'brightness').read_text().strip()
        except Exception:
            try:
                saved[str(bl)] = (bl / 'max_brightness').read_text().strip()
            except Exception:
                saved[str(bl)] = '600000'
    _BRIGHTNESS_SAVED = saved
    # Hold brightness at 0 in a tight loop; scanout stays active so kmsgrab can capture.
    script = r"""
import time, pathlib, sys
devs = sys.argv[1:]
while True:
    for d in devs:
        try:
            (pathlib.Path(d)/"brightness").write_text("0")
        except Exception:
            pass
    time.sleep(0.01)
"""
    try:
        proc = subprocess.Popen([sys.executable, '-u', '-c', script] + [str(d) for d in devs],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        _BRIGHTNESS_HOLD_PROC = proc
        return True
    except Exception:
        for bl in devs:
            try:
                (bl / 'brightness').write_text('0')
            except Exception:
                pass
        return True


def _stop_brightness_blackout():
    global _BRIGHTNESS_HOLD_PROC, _BRIGHTNESS_SAVED
    proc = _BRIGHTNESS_HOLD_PROC
    _BRIGHTNESS_HOLD_PROC = None
    if proc:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        except Exception:
            pass
    saved = _BRIGHTNESS_SAVED or {}
    _BRIGHTNESS_SAVED = None
    for d, val in saved.items():
        try:
            (Path(d) / 'brightness').write_text(str(val))
        except Exception:
            pass
    if not saved:
        for bl in _brightness_devices():
            try:
                mx = (bl / 'max_brightness').read_text().strip()
                (bl / 'brightness').write_text(mx)
            except Exception:
                pass

def _run_screen_cmd(cmd):
    try:
        if not cmd:
            return False
        exe = shutil.which(cmd[0])
        if not exe:
            # For flatpak-spawn --host, command[2] may be host tool; still try if flatpak-spawn exists
            if cmd[0] != 'flatpak-spawn':
                return False
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
        return res.returncode == 0
    except Exception:
        return False


def turn_off_screens():
    # Best-effort: blank local Deck screen while keeping scanout active (kmsgrab can capture).
    # Hold backlight at 0 in a loop so goggles can still receive the real image.
    if _start_brightness_blackout():
        return True

    def run_shell(script):
        try:
            res = subprocess.run(['bash', '-lc', script], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, timeout=6)
            return res.returncode == 0
        except Exception:
            return False

    base_cmds = [
        ['kscreen-doctor', '--dpms', 'off'],
        ['wlopm', '--off', '*'],
        ['xset', 'dpms', 'force', 'off'],
        ['xset', 'dpms', 'force', 'suspend'],
        ['busctl', '--user', 'set-property', 'org.gnome.Mutter.DisplayConfig',
         '/org/gnome/Mutter/DisplayConfig', 'org.gnome.Mutter.DisplayConfig',
         'PowerSaveMode', 'i', '1'],
        ['gdbus', 'call', '--session', '--dest', 'org.freedesktop.ScreenSaver',
         '--object-path', '/org/freedesktop/ScreenSaver', '--method',
         'org.freedesktop.ScreenSaver.SetActive', 'true'],
        ['qdbus', 'org.freedesktop.ScreenSaver', '/ScreenSaver', 'org.freedesktop.ScreenSaver.SetActive', 'true'],
        ['qdbus6', 'org.freedesktop.ScreenSaver', '/ScreenSaver', 'org.freedesktop.ScreenSaver.SetActive', 'true'],
        ['xdg-screensaver', 'activate'],
        ['dbus-send', '--session', '--dest=org.gnome.ScreenSaver',
         '--type=method_call', '/org/gnome/ScreenSaver',
         'org.gnome.ScreenSaver.SetActive', 'boolean:true'],
        ['gdbus', 'call', '--session', '--dest', 'org.gnome.ScreenSaver',
         '--object-path', '/org/gnome/ScreenSaver', '--method',
         'org.gnome.ScreenSaver.SetActive', 'true'],
        ['busctl', '--user', 'call', 'org.gnome.ScreenSaver',
         '/org/gnome/ScreenSaver', 'org.gnome.ScreenSaver', 'SetActive', 'b', 'true'],
        ['loginctl', 'lock-session'],
        ['gnome-screensaver-command', '-l'],
        ['qdbus', 'org.freedesktop.ScreenSaver', '/ScreenSaver', 'Lock'],
    ]
    any_ok = False
    for cmd in base_cmds:
        if _run_screen_cmd(cmd):
            any_ok = True

    # Backlight blank (best-effort, no restore). Works on handhelds including Steam Deck (Game Mode).
    try:
        for bl in sorted(Path('/sys/class/backlight').glob('*')):
            for name, val in (('brightness', '0'), ('bl_power', '4')):
                pth = bl / name
                if pth.exists():
                    try:
                        pth.write_text(val)
                        any_ok = True
                    except Exception:
                        try:
                            subprocess.run(['sh', '-c', f'echo {val} > {shlex.quote(str(pth))}'],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                            any_ok = True
                        except Exception:
                            pass
    except Exception:
        pass

    # GNOME/Mutter DPMS-off breaks kmsgrab capture; black overlay is preferred above.
    # (Intentionally no PowerSaveMode i 3 here.)

    # Extra KDE/Steam Deck attempts
    if run_shell('command -v kscreen-doctor >/dev/null 2>&1 && kscreen-doctor --dpms off >/dev/null 2>&1'):
        any_ok = True
    if run_shell('command -v qdbus6 >/dev/null 2>&1 && qdbus6 org.kde.Solid.PowerManagement /org/kde/Solid/PowerManagement org.kde.Solid.PowerManagement.turnOffScreen >/dev/null 2>&1'):
        any_ok = True
    if run_shell('command -v qdbus >/dev/null 2>&1 && qdbus org.kde.Solid.PowerManagement /org/kde/Solid/PowerManagement org.kde.Solid.PowerManagement.turnOffScreen >/dev/null 2>&1'):
        any_ok = True

    # If running inside Flatpak, try executing on host for better chance to affect session
    if os.environ.get('FLATPAK_ID') and shutil.which('flatpak-spawn'):
        host_cmds = [
            ['flatpak-spawn', '--host', 'bash', '-lc',
             'kscreen-doctor --dpms off 2>/dev/null || wlopm --off "*" 2>/dev/null || xset dpms force off 2>/dev/null || xset dpms force suspend 2>/dev/null || true'],
            ['flatpak-spawn', '--host', 'bash', '-lc',
             'qdbus6 org.kde.Solid.PowerManagement /org/kde/Solid/PowerManagement org.kde.Solid.PowerManagement.turnOffScreen 2>/dev/null || qdbus org.kde.Solid.PowerManagement /org/kde/Solid/PowerManagement org.kde.Solid.PowerManagement.turnOffScreen 2>/dev/null || true'],
            ['flatpak-spawn', '--host', 'bash', '-lc',
             'qdbus6 org.freedesktop.ScreenSaver /ScreenSaver org.freedesktop.ScreenSaver.SetActive true 2>/dev/null || qdbus org.freedesktop.ScreenSaver /ScreenSaver org.freedesktop.ScreenSaver.SetActive true 2>/dev/null || gdbus call --session --dest org.freedesktop.ScreenSaver --object-path /org/freedesktop/ScreenSaver --method org.freedesktop.ScreenSaver.SetActive true 2>/dev/null || xdg-screensaver activate 2>/dev/null || true'],
            ['flatpak-spawn', '--host', 'bash', '-lc',
             'gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver --method org.gnome.ScreenSaver.SetActive true 2>/dev/null || dbus-send --session --dest=org.gnome.ScreenSaver --type=method_call /org/gnome/ScreenSaver org.gnome.ScreenSaver.SetActive boolean:true 2>/dev/null || true'],
            ['flatpak-spawn', '--host', 'bash', '-lc',
             'for d in /sys/class/backlight/*; do echo 0 > "$d/brightness" 2>/dev/null; echo 4 > "$d/bl_power" 2>/dev/null; done; true'],
            ['flatpak-spawn', '--host', 'loginctl', 'lock-session'],
        ]
        for cmd in host_cmds:
            if _run_screen_cmd(cmd):
                any_ok = True
    return any_ok


def _maybe_turn_off_screens(screen_off_on_connect):
    global _SCREEN_OFF_DONE
    if not screen_off_on_connect or _SCREEN_OFF_DONE:
        return
    _SCREEN_OFF_DONE = True
    ok = turn_off_screens()
    if ok:
        print('Requested local screen off (best-effort).', flush=True)
    else:
        print('Screen-off requested, but no supported display power command succeeded (best-effort).', flush=True)


def report(row, screen_off_on_connect=False):
    event = row['event']
    if event == 'waiting':
        print(f"Waiting / reconnecting: {row['message']}", flush=True)
    elif event == 'ready':
        print(f"Found {row['model']} ({row['identity']})", flush=True)
        _maybe_turn_off_screens(screen_off_on_connect)
    elif event == 'streaming':
        print(f'Streaming {WIDTH}x{HEIGHT}. Ctrl+C stops.', flush=True)
        _maybe_turn_off_screens(screen_off_on_connect)
    elif event == 'stats':
        print(f"Sent {row['frames']} frames ({row['bytes']/1e6:.1f} MB) | "
              f"queue p95 {row['queue_ms_p95']:.1f} ms | send p95 {row['send_ms_p95']:.1f} ms | "
              f"largest frame {row['frame_bytes_max']/1000:.0f} KB | "
              f"oversize {row['oversize_frames']}", flush=True)
    elif event == 'oversize_frame':
        print(f"Skipped a {row['bytes']/1000:.0f} KB frame, over the {row['limit']/1000:.0f} KB limit. "
              'Lower --bitrate-mbps or --fps.', flush=True)
    elif event == 'encoder_restart':
        print('Restarting video after an oversized frame.', flush=True)
    elif event in ('connected', 'stopped'):
        print(event.capitalize(), flush=True)
    elif event == 'error':
        print(f"Error: {row['message']}", file=sys.stderr, flush=True)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', choices=('testsrc', 'file', 'v4l2', 'desktop'),
                        default='testsrc', help='Video source (default: testsrc)')
    parser.add_argument('--file', type=Path, help='Input file for --source file')
    parser.add_argument('--device', default='/dev/video0', help='V4L2 device for --source v4l2')
    parser.add_argument('--input-format', help='V4L2 input format, e.g. mjpeg or yuyv422')
    parser.add_argument('--input-size', help='V4L2 input size, e.g. 720x576')
    parser.add_argument('--input-fps', type=int, help='V4L2 input frame rate')
    parser.add_argument('--desktop-capture', choices=('portal', 'pipewire', 'x11grab', 'kmsgrab'),
                        default='portal',
                        help='Desktop capture backend (default: portal; kmsgrab needs root)')
    parser.add_argument('--pipewire-node', type=int, default=None,
                        help='Use an existing PipeWire node instead of opening the portal dialog')
    parser.add_argument('--kmsgrab-device', default=None,
                        help='DRM device for kmsgrab (default: first /dev/dri/card*)')
    parser.add_argument('--kmsgrab-rotate', choices=('none', '90', '180', '270'), default='none',
                        help='Rotate kmsgrab scanout (Steam Deck panels are often 90)')
    parser.add_argument('--kmsgrab-format', default='auto',
                        help='Software format after hwdownload (default: auto; e.g. x2rgb10le, bgr0)')
    parser.add_argument('--no-kmsgrab-vaapi-map', dest='kmsgrab_vaapi_map',
                        action='store_false',
                        help='Skip the DRM->VAAPI map used to decompress DCC scanout')
    parser.add_argument('--gpu-filters', choices=('auto', 'on', 'off'), default='auto',
                        help='Keep kmsgrab transpose/scale/pad on the GPU (default: auto)')
    parser.add_argument('--scaler', choices=SCALERS, default='bicubic',
                        help='Software scaler for the readback/libx264 path (default: bicubic)')
    parser.add_argument('--ffmpeg', type=Path, default=shutil.which('ffmpeg'),
                        help='FFmpeg executable (default: from PATH)')
    parser.add_argument('--encoder', choices=('auto', 'vaapi', 'libx264', 'vulkan'), default='auto')
    parser.add_argument('--vaapi-device', default='/dev/dri/renderD128')
    parser.add_argument('--fps', type=int, choices=(60, 75, 90, 100), default=60)
    parser.add_argument('--bitrate-mbps', type=int, choices=BITRATES, default=None,
                        help='Target Mbps (default: 14 with VAAPI, 16 with libx264)')
    parser.add_argument('--keyframe-seconds', type=int, choices=(1, 3), default=3)
    parser.add_argument('--capture-fps', type=int, default=60)
    parser.add_argument('--preset', default='ultrafast', help='libx264 preset (default: ultrafast)')
    parser.add_argument('--portal-rotate', choices=('none', '90', '180', '270'), default='none',
                        help='Rotate the portal stream if the compositor sends it sideways')
    parser.add_argument('--portal-encoder', choices=('auto', 'x264', 'vaapi'), default='auto',
                        help='GStreamer encoder for the portal path (default: auto)')
    parser.add_argument('--usb-write-size', type=int, choices=(2048, 16384), default=16384)
    parser.add_argument('--seconds', type=float, default=0, help='Stop after N seconds (0 = forever)')
    parser.add_argument('--route', choices=('pc', 'mobile'), default='pc',
                        help='USB/protocol route: pc (V1, default) or mobile (V2/AOA, experimental)')
    parser.add_argument('--mobile-profile', choices=('zv900', 'pigeon'), default='zv900',
                        help='Mobile V2 profile (when --route mobile)')
    parser.add_argument('--mobile-relay', default=None,
                        help='Experimental: TCP relay host:port for mobile/V2 route (external AOA relay)')
    parser.add_argument('--no-reconnect', action='store_true')
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument('--log', type=Path, help='Event log path (default: ~/.local/state/g2-bridge/logs)')
    parser.add_argument('--print-command', action='store_true',
                        help='Print the capture command and exit')
    parser.add_argument('--check', action='store_true',
                        help='Encode two frames and exit (tests capture/encoder without goggles)')
    parser.add_argument('--no-aud-bsf', action='store_true',
                        help='Keep VAAPI filler-data NALs (debugging; can cause oversized frames)')
    parser.add_argument('--screen-off-on-connect', action='store_true',
                        help='Turn off local displays when goggles connect successfully')
    parser.add_argument('-v', '--verbose', action='store_true')
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.source == 'file' and not args.file:
        parser.error('--source file needs --file')

    portal_capture = args.source == 'desktop' and args.desktop_capture == 'portal'
    portal = None
    portal_node = None

    if portal_capture:
        from goggles_bridge import gst_capture
        if not gst_capture.gst_launch():
            parser.error('gst-launch-1.0 not found. Install gstreamer1-plugins-base-tools')
        try:
            gst_capture.pick_portal_encoder(args.portal_encoder)
        except RuntimeError as exc:
            parser.error(str(exc))
        args.ffmpeg = Path(args.ffmpeg) if args.ffmpeg else Path('/nonexistent')
        if args.bitrate_mbps is None:
            # x264's frame cap is verified at 10 Mbps with a 150 ms VBV.
            args.bitrate_mbps = 10
        if args.print_command and args.pipewire_node is None:
            cmd = build_portal_command(args, 0)
            for index, item in enumerate(cmd):
                if item == 'path=0':
                    cmd[index] = 'path=<portal-node>'
            print(shlex.join(cmd))
            print('The portal chooses the PipeWire node at runtime; pass --pipewire-node '
                  'to print a concrete command.', file=sys.stderr)
            return 0
    else:
        if args.ffmpeg is None or not Path(args.ffmpeg).is_file():
            parser.error('FFmpeg not found. Install it or pass --ffmpeg /path/to/ffmpeg')
        args.ffmpeg = Path(args.ffmpeg)
        devices = run_ffmpeg_capability(args.ffmpeg, '-devices')
        if args.source == 'desktop':
            if args.desktop_capture == 'kmsgrab' and args.kmsgrab_device is None:
                cards = sorted(Path('/dev/dri').glob('card[0-9]*'))
                args.kmsgrab_device = str(cards[0]) if cards else '/dev/dri/card0'
            if args.desktop_capture == 'kmsgrab' and 'kmsgrab' not in devices:
                parser.error('This FFmpeg has no kmsgrab input')
            if args.desktop_capture == 'pipewire' and 'pipewire' not in devices:
                print('This FFmpeg has no pipewire input; falling back to x11grab', file=sys.stderr)
                args.desktop_capture = 'x11grab'
            if args.desktop_capture == 'kmsgrab' and os.geteuid() != 0:
                print('kmsgrab normally needs root: run this command with sudo', file=sys.stderr)
            if args.desktop_capture == 'kmsgrab' and args.kmsgrab_format == 'auto':
                args.kmsgrab_format = (probe_kmsgrab_format(args.ffmpeg, args.kmsgrab_device)
                                       or 'x2rgb10le')
                if args.verbose:
                    print(f'kmsgrab scanout format: {args.kmsgrab_format}', file=sys.stderr)

        encoder = pick_encoder(args)
        if args.bitrate_mbps is None:
            args.bitrate_mbps = 14 if encoder == 'vaapi' else 16
        resolve_gpu_filters(args, encoder)

    if portal_capture and args.pipewire_node is None:
        try:
            from goggles_bridge.portal import ScreenCastPortal
            portal = ScreenCastPortal()
            portal_node = portal.start(cursor=True)
        except Exception as exc:
            if portal is not None:
                portal.close()
            print(f'Portal ScreenCast failed: {exc}', file=sys.stderr)
            return 1
        print(f'Portal PipeWire node: {portal_node}', file=sys.stderr)
    elif portal_capture:
        portal_node = args.pipewire_node

    # Author's Windows limits for PC route: avg frame <= ~50 KB (bitrate/fps/8 <= 50000)
    if args.route == 'pc' and not portal_capture:
        max_avg = 50_000
        max_b = min(40, (max_avg * 8 * args.fps) // 1_000_000)
        # also keep existing per-fps caps similar to author (24@60,30@75,32@90,40@100)
        cap_map = {60: 24, 75: 30, 90: 32, 100: 40}
        max_b = min(max_b, cap_map.get(args.fps, max_b))
        if args.bitrate_mbps > max_b:
            print(f'PC route: capping bitrate {args.bitrate_mbps} -> {max_b} Mbps for {args.fps} fps (avg frame budget).', file=sys.stderr, flush=True)
            args.bitrate_mbps = max_b
    elif args.route == 'pc' and portal_capture:
        cap_map = {60: 24, 75: 30, 90: 32, 100: 40}
        max_b = cap_map.get(args.fps, 24)
        if args.bitrate_mbps > max_b:
            print(f'PC route (portal): capping bitrate {args.bitrate_mbps} -> {max_b} Mbps for {args.fps} fps.', file=sys.stderr, flush=True)
            args.bitrate_mbps = max_b

    if args.print_command:
        if portal_capture:
            print(shlex.join(build_portal_command(args, portal_node)))
        else:
            print(shlex.join(build_command(args, encoder)))
        if portal is not None:
            portal.close()
        return 0

    if args.check:
        if portal_capture:
            cmd = build_portal_command(args, portal_node, frames=2)
        else:
            cmd = build_command(args, encoder, frames=2)
        print('Running:', shlex.join(cmd), file=sys.stderr)
        try:
            row = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                 text=True, errors='replace', timeout=90)
        except subprocess.TimeoutExpired:
            print('Encoder test timed out (no frames captured)', file=sys.stderr)
            if portal is not None:
                portal.close()
            return 1
        if portal is not None:
            portal.close()
        if row.returncode == 0:
            print('Encoder test OK')
            return 0
        print('Encoder test failed:', file=sys.stderr)
        print('\n'.join((row.stderr or '').strip().splitlines()[-8:]), file=sys.stderr)
        return 1

    if portal_capture:
        install_portal_encoder(args, portal_node)
        encoder_label = f'portal/{args.portal_encoder}'
    else:
        install_linux_encoder(args, encoder)
        encoder_label = encoder
    settings = BridgeSettings(
        dll=Path('/nonexistent'),  # unused on Linux
        ffmpeg=args.ffmpeg,
        fps=args.fps,
        bitrate_mbps=args.bitrate_mbps,
        capture='external',
        capture_fps=max(args.capture_fps, args.fps),
        display_index=0,
        show_cursor=True,
        preset='p1',
        keyframe_seconds=args.keyframe_seconds,
        low_latency=True,
        usb_write_size=args.usb_write_size,
        h264_profile='high',
        route=args.route,
        mobile_profile=args.mobile_profile,
    )
    state_home = os.environ.get('XDG_STATE_HOME')
    if state_home:
        log_root = Path(state_home) / 'g2-bridge' / 'logs'
    else:
        home = Path.home()
        if os.geteuid() == 0 and os.environ.get('SUDO_USER'):
            import pwd
            home = Path(pwd.getpwnam(os.environ['SUDO_USER']).pw_dir)
        log_root = home / '.local' / 'state' / 'g2-bridge' / 'logs'
    log_path = args.log or log_root / f'{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.jsonl'
    stop = threading.Event()
    print(f'Encoder: {encoder_label}. Log: {log_path}', flush=True)
    print('Power the goggles and open More > DJI Virtual Flight.', flush=True)
    previous = signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        attempt = 0
        while not stop.is_set() and not (args.stop_file and args.stop_file.exists()):
            attempt += 1
            current_log = log_path if attempt == 1 else log_path.with_name(
                f'{log_path.stem}-restart-{attempt}{log_path.suffix}')
            mobile_transport_factory = None
            if settings.route == 'mobile':
                if args.mobile_relay:
                    if ':' not in args.mobile_relay:
                        raise SystemExit('--mobile-relay must be in host:port form')
                    host, port_s = args.mobile_relay.rsplit(':', 1)
                    try:
                        port = int(port_s)
                    except ValueError:
                        raise SystemExit('--mobile-relay port must be an integer')
                    from goggles_bridge.mobile_transport import TcpRelayTransport
                    from functools import partial
                    mobile_transport_factory = partial(TcpRelayTransport, host, port)
            bridge = BridgeEngine(settings, current_log,
                                  on_event=lambda row: report(row, args.screen_off_on_connect),
                                  stop_event=stop, stop_file=args.stop_file, duration=args.seconds,
                                  reconnect=not args.no_reconnect,
                                  mobile_transport_factory=mobile_transport_factory)
            try:
                bridge.run()
                break
            except (Exception, KeyboardInterrupt) as exc:
                if isinstance(exc, KeyboardInterrupt) or stop.is_set():
                    return 1
                if 'Capture ended' in str(exc) and args.seconds == 0 and not args.no_reconnect:
                    print(f'Capture ended, restarting... ({exc})', file=sys.stderr, flush=True)
                    continue
                print(f'Bridge stopped: {exc}', file=sys.stderr)
                return 1
    finally:
        _stop_brightness_blackout()
        signal.signal(signal.SIGINT, previous)
        if portal is not None:
            portal.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
