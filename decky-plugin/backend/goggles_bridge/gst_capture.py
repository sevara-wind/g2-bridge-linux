"""Build a GStreamer capture/encode command for the portal ScreenCast path.

FFmpeg on most Linux distributions has no PipeWire input, while GStreamer has
had ``pipewiresrc`` for years.  This module turns a portal PipeWire node id
into an AVI stream on stdout, which is exactly what ``BridgeEngine`` consumes.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess

from .engine import HEIGHT, WIDTH


def gst_launch() -> str | None:
    return shutil.which('gst-launch-1.0')


def has_element(name: str) -> bool:
    exe = shutil.which('gst-inspect-1.0')
    if not exe:
        return False
    try:
        row = subprocess.run([exe, name], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return row.returncode == 0


def pick_portal_encoder(requested: str = 'auto') -> str:
    if requested == 'x264':
        if not has_element('x264enc'):
            raise RuntimeError('GStreamer has no x264enc; install gst-plugins-ugly')
        return 'x264'
    if requested == 'vaapi':
        if not has_element('vaapih264enc'):
            raise RuntimeError('GStreamer has no vaapih264enc; install gst-vaapi')
        return 'vaapi'
    # x264 is the most widely available and its VBV cap is tested on the goggles.
    if has_element('x264enc'):
        return 'x264'
    if has_element('vaapih264enc'):
        return 'vaapi'
    raise RuntimeError('GStreamer has neither x264enc nor vaapih264enc')


def build_pipeline(node: int, *, fps: int = 60, bitrate_mbps: int = 10,
                   rotate: str = 'none', encoder: str = 'auto',
                   frames: int = 0) -> str:
    enc = pick_portal_encoder(encoder)
    source = f'pipewiresrc path={int(node)} always-copy=true'
    if frames:
        source += f' num-buffers={int(frames)}'
    # Tighter VBV to stay under goggles ~56 KB frame limit (avoid oversize_frame)
    vbv_ms = max(40, min(120, 700 // max(1, bitrate_mbps)))
    parts = [
        source,
        'queue max-size-buffers=2 leaky=downstream',
        'videoconvert',
        'videoscale add-borders=true',
    ]
    if rotate == '90':
        parts.append('videoflip method=clockwise')
    elif rotate == '180':
        parts.append('videoflip method=rotate-180')
    elif rotate == '270':
        parts.append('videoflip method=counterclockwise')
    parts += [
        'videorate',
        'videoconvert',
        f'video/x-raw,format=I420,width={WIDTH},height={HEIGHT},framerate={fps}/1',
    ]
    if enc == 'x264':
        parts += [
            'x264enc speed-preset=ultrafast tune=zerolatency pass=cbr '
            f'bitrate={bitrate_mbps * 1000} key-int-max={fps * 2} aud=true '
            'bframes=0 rc-lookahead=0 sync-lookahead=0 sliced-threads=false '
            f'vbv-buf-capacity={vbv_ms} qp-min=10 qp-max=51',
        ]
    else:
        parts += [
            'vaapih264enc rate-control=cbr '
            f'bitrate={bitrate_mbps * 1000} keyframe-period={fps * 2} '
            'max-bframes=0 aud=true',
        ]
    parts += ['h264parse config-interval=-1', 'avimux', 'fdsink fd=1 sync=false']
    return ' ! '.join(parts)


def build_command(node: int, *, fps: int = 60, bitrate_mbps: int = 10,
                  rotate: str = 'none', encoder: str = 'auto',
                  frames: int = 0) -> list[str]:
    exe = gst_launch()
    if not exe:
        raise RuntimeError('gst-launch-1.0 not found; install gstreamer1-plugins-base-tools')
    pipeline = build_pipeline(node, fps=fps, bitrate_mbps=bitrate_mbps,
                              rotate=rotate, encoder=encoder, frames=frames)
    # gst-launch's CLI splits the pipeline on argv; it does not parse a single
    # quoted string like gst_parse_launch() does.
    return [exe, '-q', '-e'] + shlex.split(pipeline)
