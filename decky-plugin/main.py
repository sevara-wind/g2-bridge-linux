import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import decky

STOP_DIR = Path("/tmp")

FPS_CHOICES = ("60", "75", "90", "100")
BITRATE_CHOICES = ("8", "10", "12", "14", "16", "18", "20", "24", "30", "32", "40")
KEYFRAME_CHOICES = ("1", "3")
PRESET_CHOICES = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium")
ROTATION_CHOICES = ("none", "90", "180", "270")


def _plugin_dir():
    return Path(decky.DECKY_PLUGIN_DIR)


def _backend_dir():
    return _plugin_dir() / "backend"


def _config_path():
    return Path(decky.DECKY_PLUGIN_SETTINGS_DIR) / "settings.json"


def _defaults():
    return {
        "rotation": "270",
        "bitrate": "40",
        "fps": "100",
        "keyframe_seconds": "3",
        "preset": "ultrafast",
        "screen_off": False,
    }


def _normalize(settings):
    s = _defaults()
    if isinstance(settings, dict):
        s.update({k: settings[k] for k in s.keys() if k in settings})
    s["rotation"] = str(s.get("rotation", "270"))
    if s["rotation"] not in ROTATION_CHOICES:
        s["rotation"] = "270"
    s["bitrate"] = str(s.get("bitrate", "40"))
    if s["bitrate"] not in BITRATE_CHOICES:
        s["bitrate"] = "40"
    s["fps"] = str(s.get("fps", "100"))
    if s["fps"] not in FPS_CHOICES:
        s["fps"] = "100"
    s["keyframe_seconds"] = str(s.get("keyframe_seconds", "3"))
    if s["keyframe_seconds"] not in KEYFRAME_CHOICES:
        s["keyframe_seconds"] = "3"
    s["preset"] = str(s.get("preset", "ultrafast"))
    if s["preset"] not in PRESET_CHOICES:
        s["preset"] = "ultrafast"
    s["screen_off"] = bool(s.get("screen_off", False))
    return s


def _load_settings():
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return _normalize(data)


def _save_settings(settings):
    s = _normalize(settings)
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return s


def _find_python():
    for name in ("python3", "python"):
        p = shutil.which(name)
        if p:
            return p
    return sys.executable or "python3"


class Plugin:
    proc = None
    log_lines = None
    stop_file = None
    lock = None
    reader_thread = None

    async def _main(self):
        self.proc = None
        self.log_lines = []
        self.stop_file = None
        self.lock = threading.Lock()
        self.reader_thread = None
        decky.logger.info("G2 Bridge plugin loaded")

    async def _unload(self):
        try:
            self._stop_internal()
        except Exception as e:
            decky.logger.exception("G2 Bridge unload stop error: %s", e)
        decky.logger.info("G2 Bridge plugin unloaded")

    def _append_log(self, line):
        msg = str(line).rstrip("\n")
        with self.lock:
            self.log_lines.append(msg)
            if len(self.log_lines) > 500:
                self.log_lines = self.log_lines[-500:]
        try:
            decky.logger.info("G2Bridge: %s", msg[:500])
        except Exception:
            pass

    def _reader(self, proc):
        try:
            if proc.stdout:
                for line in proc.stdout:
                    self._append_log(line)
        except Exception as e:
            self._append_log(f"[reader error] {e}")
        try:
            proc.wait()
        except Exception:
            pass
        self._append_log(f"[exit code {proc.returncode}]")

    async def get_status(self):
        running = self.proc is not None and self.proc.poll() is None
        code = None
        if self.proc is not None and self.proc.poll() is not None:
            code = self.proc.returncode
        with self.lock:
            tail = list(self.log_lines[-80:])
        return {"running": running, "exit_code": code, "log": tail, "settings": _load_settings()}

    async def get_settings(self):
        return _load_settings()

    async def save_settings(self, settings=None, **kwargs):
        if settings is None:
            settings = kwargs
        else:
            merged = dict(settings)
            merged.update(kwargs)
            settings = merged
        s = _save_settings(settings)
        return s

    def _stop_internal(self):
        proc = self.proc
        sf = self.stop_file
        if sf:
            try:
                sf.write_text("stop\n", encoding="utf-8")
            except Exception:
                pass
        if proc and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGINT)
            except Exception:
                pass
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            subprocess.run(["pkill", "-INT", "-f", "backend/scripts/stream_linux.py"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except Exception:
            pass
        self._append_log("Stop requested")

    async def stop_stream(self, **kwargs):
        self._stop_internal()
        return {"ok": True}

    async def clear_log(self, **kwargs):
        with self.lock:
            self.log_lines = []
        return {"ok": True}

    async def start_stream(self, settings=None, **kwargs):
        if settings is None:
            settings = kwargs
        else:
            merged = dict(settings)
            merged.update(kwargs)
            settings = merged
        s = _save_settings(settings if settings else _load_settings())

        if self.proc is not None and self.proc.poll() is None:
            msg = "Already running"
            self._append_log(msg)
            return {"ok": False, "error": msg}

        backend = _backend_dir()
        script = backend / "scripts" / "stream_linux.py"
        py = _find_python()
        if not script.exists():
            msg = f"Bundled script not found: {script}. Reinstall plugin."
            self._append_log(msg)
            return {"ok": False, "error": msg}

        stop_file = STOP_DIR / f"g2-bridge-decky-{os.getpid()}-{int(time.time())}"
        try:
            if stop_file.exists():
                stop_file.unlink()
        except Exception:
            pass
        self.stop_file = stop_file

        cmd = [
            py, str(script),
            "--source", "desktop", "--desktop-capture", "kmsgrab",
            "--encoder", "libx264", "--preset", s["preset"],
            "--kmsgrab-rotate", s["rotation"],
            "--gpu-filters", "off",
            "--fps", s["fps"], "--capture-fps", s["fps"],
            "--bitrate-mbps", s["bitrate"],
            "--keyframe-seconds", s["keyframe_seconds"],
            "--stop-file", str(stop_file),
        ]
        if s.get("screen_off"):
            cmd += ["--screen-off-on-connect"]

        env = os.environ.copy()
        extra_pp = [str(backend), str(backend / "py_modules")]
        env["PYTHONPATH"] = os.pathsep.join(extra_pp + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))

        self._append_log("Starting: " + " ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                cwd=str(backend),
            )
        except Exception as e:
            self.stop_file = None
            msg = f"Launch error: {e}"
            self._append_log(msg)
            return {"ok": False, "error": msg}

        self.proc = proc
        t = threading.Thread(target=self._reader, args=(proc,), daemon=True)
        t.start()
        self.reader_thread = t
        time.sleep(0.4)
        if proc.poll() is not None:
            msg = f"Process exited immediately (code {proc.returncode}). See log."
            self._append_log(msg)
            return {"ok": False, "error": msg}
        return {"ok": True, "settings": s}
