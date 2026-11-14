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


def _plugin_dir():
    return Path(decky.DECKY_PLUGIN_DIR)


def _backend_dir():
    # Bundled backend inside plugin (autonomous, no external project required)
    return _plugin_dir() / "backend"


def _config_path():
    return Path(decky.DECKY_PLUGIN_SETTINGS_DIR) / "settings.json"


def _load_settings():
    defaults = {
        "bitrate": "40",
        "rotation": "270",
        "screen_off": False,
    }
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for k in ("bitrate", "rotation", "screen_off"):
                if k in data:
                    defaults[k] = data[k]
    except Exception:
        pass
    defaults["bitrate"] = str(defaults.get("bitrate", "40"))
    if defaults["bitrate"] not in ("8", "10", "12", "16", "20", "24", "30", "32", "40"):
        defaults["bitrate"] = "40"
    defaults["rotation"] = str(defaults.get("rotation", "270"))
    if defaults["rotation"] not in ("none", "90", "180", "270"):
        defaults["rotation"] = "270"
    defaults["screen_off"] = bool(defaults.get("screen_off", False))
    return defaults


def _save_settings(settings):
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _find_python():
    # Prefer system python3; bundled deps are in backend/py_modules.
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
        decky.logger.info("G2 Bridge plugin loaded (autonomous)")

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
            if len(self.log_lines) > 400:
                self.log_lines = self.log_lines[-400:]
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
            tail = list(self.log_lines[-60:])
        return {"running": running, "exit_code": code, "log": tail, "settings": _load_settings()}

    async def get_settings(self):
        return _load_settings()

    async def save_settings(self, bitrate=None, rotation=None, screen_off=None, **kwargs):
        s = _load_settings()
        if bitrate is not None:
            s["bitrate"] = str(bitrate)
        if rotation is not None:
            s["rotation"] = str(rotation)
        if screen_off is not None:
            s["screen_off"] = bool(screen_off)
        s = {**_load_settings(), **s}
        _save_settings(s)
        return s

    async def start_stream(self, bitrate=None, rotation=None, screen_off=None, **kwargs):
        s = await self.save_settings(bitrate=bitrate, rotation=rotation, screen_off=screen_off)
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
            "--encoder", "libx264", "--preset", "ultrafast",
            "--kmsgrab-rotate", s["rotation"],
            "--gpu-filters", "off",
            "--fps", "100", "--capture-fps", "100",
            "--bitrate-mbps", s["bitrate"],
            "--keyframe-seconds", "3",
            "--stop-file", str(stop_file),
        ]
        if s.get("screen_off"):
            cmd += ["--screen-off-on-connect"]

        env = os.environ.copy()
        pp = backend / "py_modules"
        extra_pp = [str(backend), str(pp)]
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
        return {"ok": True}

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
