"""Capture the desktop and stream H.264 over the Goggles 2 PC USB route."""
from contextlib import closing
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

from .annexb import AccessUnitStream, is_idr
from .avi import AviPacketStream
from .control import V1Stream
from .pc_video import PcVideoPacketizer
from .protocol import VideoPacketizer as MobileVideoPacketizer, PROFILES as MOBILE_PROFILES
from .session import ControlSession, SessionLost
from .usb_transport import ControlUsb, UsbTransportError, USB_WRITE_SIZES
from .mobile_transport import MobileTransportError, TcpRelayTransport
from .mobile_session import MobileSession, MobileSessionError

# the frame size the goggles display
WIDTH, HEIGHT = 1920, 1080
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
CHOICES = dict(fps=(60, 75, 90, 100), bitrate_mbps=(8, 10, 12, 16, 20, 24, 30, 32, 40),
               capture=('external',), preset=('p1', 'p4'),
               keyframe_seconds=(1, 3), h264_profile=('baseline', 'high'), usb_write_size=USB_WRITE_SIZES,
               route=('pc', 'mobile'))
# Goggles 2 displayed frames up to 49 KB, but keyframes of about 65 KB froze it or left it
# black until a power cycle. The encoder buffer is capped at this size, and larger frames aren't sent
MAX_FRAME_BYTES = 56_000
MOBILE_MAX_FRAME_BYTES = 65_404
MAX_VBV_BITS = MAX_FRAME_BYTES * 8
# Largest tested average frame, 40 Mbps at 100 fps
MAX_AVERAGE_FRAME_BYTES = 50_000
# seconds without a picture before the encoder restarts
SILENT_SECONDS = 5


def find_program(name):
    return shutil.which(name)


@dataclass(frozen=True)
class BridgeSettings:
    dll: Path | None = None
    ffmpeg: Path | None = None
    fps: int = 100
    bitrate_mbps: int | None = None
    capture: str = 'external'
    capture_fps: int | None = None
    display_index: int = 0
    show_cursor: bool = True
    preset: str = 'p1'
    keyframe_seconds: int = 3
    low_latency: bool = True
    usb_write_size: int = 16384
    h264_profile: str = 'high'
    adaptive_quant: bool = False
    route: str = 'pc'
    mobile_profile: str = 'zv900'

    @property
    def nvenc(self):
        return False

    @property
    def max_frame_bytes(self):
        return MOBILE_MAX_FRAME_BYTES if self.route == 'mobile' else MAX_FRAME_BYTES

    def __post_init__(self):
        def check(name):
            value, choices = getattr(self, name), CHOICES[name]
            if type(value) is not type(choices[0]) or value not in choices:
                raise ValueError(f'Unsupported {name}: {value}')

        check('fps')
        for name in ('low_latency', 'adaptive_quant'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} must be a boolean')
        for name in CHOICES:
            check(name)
        if self.route == 'mobile' and self.mobile_profile not in MOBILE_PROFILES:
            raise ValueError(f'Unsupported mobile profile: {self.mobile_profile}')
        if self.bitrate_mbps is None:
            if self.route == 'mobile':
                object.__setattr__(self, 'bitrate_mbps', 20)
            else:
                object.__setattr__(self, 'bitrate_mbps',
                                   min(40, self.fps * 8 * MAX_AVERAGE_FRAME_BYTES // 1_000_000))
        # The buffer cap bounds keyframes, but in CBR every frame averages bitrate/fps (PC route)
        if self.route == 'pc' and self.bitrate_mbps * 1_000_000 // (8 * self.fps) > MAX_AVERAGE_FRAME_BYTES:
            limit = max(b for b in CHOICES['bitrate_mbps'] if b * 1_000_000 // (8 * self.fps) <= MAX_AVERAGE_FRAME_BYTES)
            raise ValueError(f'At {self.fps} fps, use at most {limit} Mbps. '
                             f'{self.bitrate_mbps} Mbps makes frames too large for the goggles')
        if self.capture_fps is None:
            object.__setattr__(self, 'capture_fps', 240)
        if type(self.capture_fps) is not int or not self.fps <= self.capture_fps <= 1000:
            raise ValueError('Capture ceiling must be between output fps and 1000')
        if type(self.display_index) is not int or self.display_index < 0:
            raise ValueError('Display index must be a nonnegative integer')


def encoder_command(settings, frames=0):
    """External capture pipelines provide their own encoder command (see stream_linux.py)."""
    raise NotImplementedError('External capture requires a custom encoder command')


def check_encoder(settings, run=subprocess.run):
    """External capture pipelines handle their own encoder checks."""
    return None


def prioritize_gpu(process):
    """Give the encoder realtime GPU scheduling so a saturated simulator cannot queue ahead of it.

    Call it once the process has produced output: the kernel rejects processes that
    have not yet created a graphics context. Needs no elevation. Under synthetic GPU
    saturation it cut the capture-to-packet p95 from about 6.7 to 3.5 ms; the HIGH
    class changed nothing. Returns False where unsupported.
    """
    handle = getattr(process, '_handle', None)
    if handle is None or sys.platform != 'win32':
        return False
    import ctypes
    set_class = ctypes.WinDLL('gdi32').D3DKMTSetProcessSchedulingPriorityClass
    set_class.argtypes = [ctypes.c_void_p, ctypes.c_int]
    return set_class(int(handle), 5) == 0  # D3DKMT_SCHEDULINGPRIORITYCLASS_REALTIME


class EventLog:
    """Write timestamped JSON Lines rows to a new file."""
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open('x', encoding='utf-8')
        self.started = time.perf_counter()

    def __call__(self, event, **fields):
        row = dict(seconds=round(time.perf_counter()-self.started, 6), event=event, **fields)
        self.stream.write(json.dumps(row)+'\n')
        self.stream.flush()
        return row

    def close(self):
        self.stream.close()


class BridgeEngine:
    """Manage the encoder and USB session, reconnecting after link loss."""
    def __init__(self, settings, log_path, *, on_event=None, stop_event=None,
                 stop_file=None, duration=0, reconnect=True, retry_delay=1,
                 transport_factory=None, mobile_transport_factory=None,
                 process_factory=subprocess.Popen):
        if not math.isfinite(duration) or duration < 0:
            raise ValueError('Duration must be nonnegative and finite')
        if not math.isfinite(retry_delay) or retry_delay < 0:
            raise ValueError('Retry delay must be nonnegative and finite')
        self.settings = settings
        self.log_path = Path(log_path)
        self.on_event = on_event or (lambda event: None)
        self.stop_event = stop_event or threading.Event()
        self.stop_file = Path(stop_file) if stop_file else None
        self.duration = duration
        self.reconnect = reconnect
        self.retry_delay = retry_delay
        self.mobile_transport_factory = mobile_transport_factory
        if transport_factory is None:
            if settings.route == 'mobile':
                if mobile_transport_factory is not None:
                    transport_factory = mobile_transport_factory
                else:
                    transport_factory = None  # must be provided for mobile route
            else:
                transport_factory = partial(ControlUsb, write_size=settings.usb_write_size)
        self.transport_factory = transport_factory
        self.process_factory = process_factory
        self.log = None
        self.waiting = None

    def stopping(self):
        return (self.stop_event.is_set() or (self.stop_file is not None and self.stop_file.exists())
                or (self.duration > 0 and time.perf_counter()-self.log.started >= self.duration))

    def emit(self, event, **fields):
        self.on_event(self.log(event, **fields))

    def run(self):
        with closing(EventLog(self.log_path)) as self.log:
            settings = {name: value for name, value in asdict(self.settings).items() if name not in ('dll', 'ffmpeg')}
            self.emit('starting', resolution=f'{WIDTH}x{HEIGHT}', intra_refresh=self.settings.nvenc,
                      multipass='qres' if self.settings.nvenc else 'disabled', **settings)
            try:
                attempt = 0
                while not self.stopping():
                    attempt += 1
                    try:
                        self._session(attempt)
                    except (UsbTransportError, SessionLost) as exc:
                        if not self.reconnect:
                            raise
                        if self.waiting != str(exc):
                            self.emit('waiting', message=str(exc))
                        self.waiting = str(exc)
                        retry_at = time.perf_counter()+self.retry_delay
                        while not self.stopping() and time.perf_counter() < retry_at:
                            self.stop_event.wait(min(.1, max(0, retry_at-time.perf_counter())))
            except Exception as exc:
                self.emit('error', message=str(exc))
                raise
            finally:
                self.emit('stopped')

    def _session(self, attempt):
        local_stop = threading.Event()
        incoming = queue.Queue(maxsize=256)
        frames = queue.Queue(maxsize=1 if self.settings.low_latency else 3)
        errors = queue.Queue()
        is_mobile = self.settings.route == 'mobile'
        if is_mobile:
            session = MobileSession()
            decoder = None
            packetizer = MobileVideoPacketizer(self.settings.mobile_profile)
            discarded_bytes = 0
        else:
            session = ControlSession()
            decoder = V1Stream()
            packetizer = PcVideoPacketizer()
        process = None
        encoder_thread = None
        encoder_stop = threading.Event()
        encoder_first_frame = True
        restart_attempts = 0
        last_restart = None
        threads = []
        frame_count = byte_count = previous_frames = oversize_count = largest_frame = 0
        resync = False
        queue_times, send_times = [], []
        last_frame = last_progress = time.perf_counter()
        encoder_path = self.log_path.with_name(f'{self.log_path.stem}.encoder-{attempt}.log')
        max_frame_bytes = self.settings.max_frame_bytes
        if self.transport_factory is None:
            raise RuntimeError('Mobile route requires a mobile transport (e.g. --mobile-relay host:port). '
                               'Native USB gadget/AOA transport is not available on this kernel.')
        transport_ctx = self.transport_factory() if is_mobile else self.transport_factory(self.settings.dll)
        with transport_ctx as usb:
            self.emit('connected', attempt=attempt, route=self.settings.route)

            def read_usb():
                try:
                    while not local_stop.is_set():
                        data = usb.read(timeout_ms=500)
                        if data:
                            incoming.put(data, timeout=.2)
                except Exception as exc:
                    if not local_stop.is_set():
                        errors.put(exc)

            def read_encoder(encoder):
                splitter = AviPacketStream() if self.settings.low_latency else AccessUnitStream()
                try:
                    while not local_stop.is_set() and not encoder_stop.is_set():
                        data = encoder.stdout.read(16384)
                        if not data:
                            raise RuntimeError(f'Capture ended. See {encoder_path}')
                        for frame in splitter.feed(data):
                            completed_at = time.perf_counter()
                            while not local_stop.is_set() and not encoder_stop.is_set():
                                try:
                                    frames.put((completed_at, frame), timeout=.1)
                                    break
                                except queue.Full:
                                    pass
                except Exception as exc:
                    if not local_stop.is_set() and not encoder_stop.is_set():
                        errors.put(exc)

            def stop_encoder():
                nonlocal process, encoder_thread
                encoder_stop.set()
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                if process and process.stdout:
                    process.stdout.close()
                if encoder_thread:
                    encoder_thread.join(timeout=1)
                    if encoder_thread.is_alive():
                        raise RuntimeError('Encoder reader did not stop')
                process = encoder_thread = None
                while not frames.empty():
                    frames.get_nowait()

            def start_encoder():
                nonlocal process, encoder_thread, encoder_first_frame, last_frame
                encoder_stop.clear()
                # restarts append to the session's log, and the encoder keeps its own handle
                with encoder_path.open('a', encoding='utf-8') as encoder_log:
                    process = self.process_factory(encoder_command(self.settings), stdout=subprocess.PIPE,
                        stderr=encoder_log, stdin=subprocess.DEVNULL, bufsize=0, creationflags=NO_WINDOW)
                last_frame = time.perf_counter()
                encoder_first_frame = True
                encoder_thread = threading.Thread(target=read_encoder, args=(process,), daemon=True)
                encoder_thread.start()

            def send_control(packet):
                data = packet.serialize()
                usb.write(data)
                self.emit('control_send', hex=data.hex())

            try:
                thread = threading.Thread(target=read_usb, daemon=True)
                threads.append(thread)
                thread.start()
                while not self.stopping():
                    if not errors.empty():
                        raise errors.get_nowait()
                    # Accept queued replies before judging their deadlines
                    while not incoming.empty():
                        data = incoming.get_nowait()
                        self.emit('control_receive', hex=data.hex())
                        if decoder is not None:
                            for reply in decoder.feed(data):
                                for packet in session.receive(reply, time.perf_counter()):
                                    send_control(packet)
                        else:
                            # Mobile route: control/session protocol TBD; ignore incoming for now.
                            discarded_bytes += 0
                    for packet in session.poll(time.perf_counter()):
                        if hasattr(packet, 'serialize'):
                            send_control(packet)
                    if session.state == 'ready' and process is None:
                        self.waiting = None
                        self.emit('ready', model=session.model, identity=session.identity)
                        start_encoder()
                    if session.state == 'ready':
                        try:
                            completed_at, frame = frames.get(timeout=.002)
                        except queue.Empty:
                            if time.perf_counter()-last_frame > SILENT_SECONDS:
                                if encoder_first_frame:
                                    raise RuntimeError(f'No video from display. See {encoder_path}')
                                # FFmpeg 9.0 sends no pictures on a still screen, and a new encoder starts with keyframes
                                stop_encoder()
                                start_encoder()
                                self.emit('capture_restart')
                            continue
                        last_frame = time.perf_counter()
                        oversize = len(frame) > max_frame_bytes
                        if oversize:
                            oversize_count += 1
                            self.emit('oversize_frame', bytes=len(frame), limit=max_frame_bytes)
                            # Drop oversized frames and resync to next IDR to keep stream alive.
                            # Restart encoder only if oversize persists in a short window.
                            if last_restart is None or last_frame-last_restart >= 8:
                                restart_attempts = 0
                            restart_attempts += 1
                            last_restart = last_frame
                            resync = True
                            if restart_attempts in (5, 15, 30):
                                stop_encoder()
                                if not self.stopping():
                                    start_encoder()
                                    self.emit('encoder_restart', attempt=restart_attempts)
                            if restart_attempts >= 60:
                                raise RuntimeError('Encoded frames repeatedly exceed the size limit. Lower the bitrate')
                            continue
                        # Later frames reference a skipped one, so resume only at a keyframe that fits
                        if resync and not is_idr(frame):
                            continue
                        resync = False
                        largest_frame = max(largest_frame, len(frame))
                        queue_times.append((last_frame-completed_at)*1000)
                        if is_mobile:
                            packets = packetizer.packetize(frame)
                            wire = b''.join(packets)
                        else:
                            wire = b''.join(packetizer.packetize(frame, session.reserve_sequence))
                        usb.write(wire)
                        send_times.append((time.perf_counter()-last_frame)*1000)
                        byte_count += len(wire)
                        frame_count += 1
                        if encoder_first_frame:
                            self.emit('streaming', encoder_pid=process.pid, gpu_realtime=prioritize_gpu(process))
                            encoder_first_frame = False
                    else:
                        self.stop_event.wait(.002)
                    now = time.perf_counter()
                    if now-last_progress >= 5:
                        def p95(values):
                            return round(sorted(values)[int((len(values)-1)*.95)], 2) if values else 0
                        self.emit('stats', frames=frame_count, bytes=byte_count, queued_frames=frames.qsize(),
                                  fps=round((frame_count-previous_frames)/(now-last_progress), 2),
                                  queue_ms_p95=p95(queue_times), send_ms_p95=p95(send_times),
                                  frame_bytes_max=largest_frame, oversize_frames=oversize_count)
                        previous_frames, last_progress, largest_frame = frame_count, now, 0
                        queue_times.clear()
                        send_times.clear()
            finally:
                local_stop.set()
                try:
                    stop_encoder()
                finally:
                    for thread in threads:
                        thread.join(timeout=1)
                    self.emit('session_ended', frames=frame_count, bytes=byte_count,
                              discarded_bytes=(decoder.discarded if decoder is not None else discarded_bytes))
