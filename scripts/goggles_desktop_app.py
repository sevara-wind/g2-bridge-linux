#!/usr/bin/env python3
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'goggles_bridge' / 'app' / 'ui'

# Etalon Linux profile base (mapped to our stream_linux.py)
CHOICES = {
    'fps': [60, 75, 90, 100],
    'capture': ('kmsgrab',),
    'preset': ('ultrafast',),
    'keyframe_seconds': [1, 3],
    'h264_profile': ('high',),
    'usb_write_size': [16384],
}


def data_dir():
    base = os.environ.get('XDG_DATA_HOME') or os.path.join(Path.home(), '.local', 'share')
    return Path(base) / 'g2-bridge'


def config_path():
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(Path.home(), '.config')
    return Path(base) / 'g2-bridge' / 'settings.json'


def log_dir():
    base = os.environ.get('XDG_STATE_HOME') or os.path.join(Path.home(), '.local', 'state')
    return Path(base) / 'g2-bridge' / 'logs'


def _runtime_dir():
    # Use host-visible shared location (xdg-data/g2-bridge) so flatpak-spawn --host can access it.
    return Path(os.path.expanduser('~/.local/share/g2-bridge/runtime'))


def _deploy_runtime():
    src = ROOT
    dst = _runtime_dir()
    dst.mkdir(parents=True, exist_ok=True)
    import shutil
    for name in ('goggles_bridge', 'scripts', 'vendor'):
        s = src / name
        if not s.exists():
            continue
        d = dst / name
        if d.exists():
            shutil.rmtree(d)
        shutil.copytree(s, d, dirs_exist_ok=True)
    for bindir in (src / 'bin', src.parent.parent / 'bin', Path('/app/bin')):
        if bindir.exists() and bindir.is_dir():
            out = dst / 'bin'
            out.mkdir(parents=True, exist_ok=True)
            for f in bindir.iterdir():
                if f.is_file():
                    try:
                        shutil.copy2(f, out / f.name)
                        (out / f.name).chmod(0o755)
                    except Exception:
                        pass
            break


def _runtime_pythonpath(runtime):
    pp = [str(runtime), str(runtime / 'vendor')]
    vendor = runtime / 'vendor'
    if vendor.exists():
        for whl in vendor.glob('*.whl'):
            pp.append(str(whl))
    return ':'.join(pp)


def default_options():
    return {
        'display_index': 0,
        'fps': 100,
        'bitrate_mbps': 40,
        'show_cursor': False,
        'capture': 'kmsgrab',
        'keyframe_seconds': 3,
        'h264_profile': 'high',
        'preset': 'ultrafast',
        'adaptive_quant': False,
        'low_latency': True,
        'usb_write_size': 16384,
        'rotation': '270',
        'screen_off': False,
    }


class LinuxDesktopBackend:
    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        self._reader = None
        self._stop_file = None
        self._log_path = None
        self._quit = lambda: None
        self._options = default_options()
        self._onboarded = False
        self._state = {
            'phase': 'idle',
            'problem': None,
            'stats': None,
            'oversize': 0,
            'log': None,
        }
        self._device = None
        self._load_settings()

    def _load_settings(self):
        try:
            data = json.loads(config_path().read_text(encoding='utf-8'))
            if isinstance(data, dict):
                self._onboarded = bool(data.get('onboarded', False))
                for k in self._options:
                    if k in data:
                        self._options[k] = data[k]
        except Exception:
            pass
        self._normalize_options()

    def _save(self):
        p = config_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            out = dict(self._options)
            out['onboarded'] = self._onboarded
            p.write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        except Exception:
            pass

    def _normalize_options(self):
        o = self._options
        try:
            o['fps'] = int(o.get('fps', 100))
        except Exception:
            o['fps'] = 100
        if o['fps'] not in CHOICES['fps']:
            o['fps'] = 100
        try:
            o['bitrate_mbps'] = int(o.get('bitrate_mbps', 40))
        except Exception:
            o['bitrate_mbps'] = 40
        allowed = self._bitrates_for(o['fps'])
        if o['bitrate_mbps'] not in allowed:
            o['bitrate_mbps'] = max([b for b in allowed if b <= o['bitrate_mbps']] or [allowed[0]])
        o['keyframe_seconds'] = 3 if int(o.get('keyframe_seconds', 3)) == 3 else 1
        o['rotation'] = str(o.get('rotation', '270'))
        if o['rotation'] not in ('none', '90', '180', '270'):
            o['rotation'] = '270'
        o['screen_off'] = bool(o.get('screen_off', False))
        # fixed for Linux kmsgrab etalon
        o['capture'] = 'kmsgrab'
        o['preset'] = 'ultrafast'
        o['h264_profile'] = 'high'
        o['usb_write_size'] = 16384
        o['display_index'] = 0
        o['show_cursor'] = bool(o.get('show_cursor', False))
        o['adaptive_quant'] = False
        o['low_latency'] = True

    def _bitrates_for(self, fps):
        # Keep within PC cap logic roughly; allow common values
        allowed = [8, 10, 12, 16, 20, 24, 30, 32, 40]
        if fps >= 100:
            return [b for b in allowed if b <= 40]
        return allowed

    def _running(self):
        return self._proc is not None and self._proc.poll() is None

    def snapshot(self):
        with self._lock:
            phase = self._state['phase']
            problem = dict(self._state['problem']) if self._state['problem'] else None
            stats = dict(self._state['stats']) if self._state['stats'] else None
            oversize = self._state['oversize']
            log = self._state['log']
            running = self._running()
            opts = dict(self._options)
            onboarded = self._onboarded
            device = self._device
        if not running and phase not in ('idle', 'error'):
            phase = 'idle'
        checks = {
            'driver': {'needed': False, 'ok': True},
            'screen': {'needed': False, 'ok': True},
            'ffmpeg': {'needed': True, 'ok': True},
            'attached': True,  # not reliably detectable without extra probing here
        }
        displays = [{'index': 0, 'name': 'Display 1', 'x': 0, 'y': 0, 'width': 1920, 'height': 1080, 'hz': 60, 'primary': True}]
        bitrates = {str(f): {'allowed': self._bitrates_for(f), 'auto': 40 if f >= 100 else 32} for f in CHOICES['fps']}
        return {
            'app': {'name': 'Goggles Bridge', 'version': 'linux', 'platform': sys.platform, 'updatable': False},
            'checks': checks,
            'displays': displays,
            'options': opts,
            'choices': {
                'fps': CHOICES['fps'],
                'capture': list(CHOICES['capture']),
                'preset': list(CHOICES['preset']),
                'keyframe_seconds': CHOICES['keyframe_seconds'],
                'h264_profile': list(CHOICES['h264_profile']),
                'usb_write_size': CHOICES['usb_write_size'],
                'bitrates': bitrates,
            },
            'frame_limit': 56000,
            'onboarded': onboarded,
            'phase': phase,
            'problem': problem,
            'stats': stats,
            'oversize': oversize,
            'log': log,
            'device': device,
        }

    def set_options(self, options=None, **kwargs):
        if options is None:
            options = kwargs
        with self._lock:
            if self._running():
                return {'error': 'To change settings, stop streaming.'}
            self._options.update({k: v for k, v in (options or {}).items() if k in self._options})
            self._normalize_options()
            self._save()
        return {'ok': True}

    def finish_setup(self):
        with self._lock:
            self._onboarded = True
            self._save()
        return {'ok': True}

    def _build_cmd(self):
        o = dict(self._options)
        args = [
            '--source', 'desktop', '--desktop-capture', 'kmsgrab',
            '--encoder', 'libx264', '--preset', 'ultrafast',
            '--kmsgrab-rotate', str(o.get('rotation', '270')),
            '--gpu-filters', 'off',
            '--fps', str(o.get('fps', 100)),
            '--capture-fps', str(o.get('fps', 100)),
            '--bitrate-mbps', str(o.get('bitrate_mbps', 40)),
            '--keyframe-seconds', str(o.get('keyframe_seconds', 3)),
        ]
        if o.get('screen_off'):
            args += ['--screen-off-on-connect']

        if os.environ.get('FLATPAK_ID'):
            try:
                _deploy_runtime()
            except Exception:
                pass
            runtime = _runtime_dir()
            host_python = os.environ.get('G2_BRIDGE_HOST_PYTHON', 'python3')
            host_script = str(runtime / 'scripts' / 'stream_linux.py')
            pp = _runtime_pythonpath(runtime)
            path_env = os.environ.get('PATH', '/usr/bin:/bin')
            bin_dir = runtime / 'bin'
            if bin_dir.exists():
                path_env = f"{bin_dir}:{path_env}"
            return ['flatpak-spawn', '--host', 'pkexec', 'env', f'PYTHONPATH={pp}', f'PATH={path_env}', host_python, host_script] + args
        return [sys.executable, str(ROOT / 'scripts' / 'stream_linux.py')] + args

    def start(self):
        with self._lock:
            if self._running():
                return {'ok': True}
            log_dir().mkdir(parents=True, exist_ok=True)
            log = log_dir() / f'{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.jsonl'
            self._log_path = log
            self._state = {'phase': 'checking', 'problem': None, 'stats': None, 'oversize': 0, 'log': str(log)}
            self._device = None
            cmd = self._build_cmd()
            stop_name = f'g2-bridge-stop-{os.getpid()}-{int(time.time())}'
            if os.environ.get('FLATPAK_ID'):
                stop_file = f'/tmp/{stop_name}'
                try:
                    subprocess.run(['flatpak-spawn', '--host', 'rm', '-f', stop_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                except Exception:
                    pass
            else:
                stop_file = f'/tmp/{stop_name}'
                try:
                    Path(stop_file).unlink(missing_ok=True)
                except Exception:
                    pass
            self._stop_file = stop_file
            cmd = cmd + ['--stop-file', stop_file]
            try:
                self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            except Exception as e:
                self._proc = None
                self._stop_file = None
                self._state.update(phase='error', problem={'code': 'encoder', 'message': f'Launch error: {e}'})
                return {'ok': False}
            t = threading.Thread(target=self._read_output, daemon=True)
            t.start()
            self._reader = t
        return {'ok': True}

    def _read_output(self):
        proc = self._proc
        if proc is None:
            return
        try:
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                self._handle_line(line.rstrip('\n'))
        except Exception:
            pass
        try:
            proc.wait()
        except Exception:
            pass
        with self._lock:
            if self._state.get('phase') != 'error':
                self._state.update(phase='idle', problem=None, stats=None)
            self._proc = None
            sf = self._stop_file
            self._stop_file = None
        if sf:
            try:
                if os.environ.get('FLATPAK_ID'):
                    subprocess.run(['flatpak-spawn', '--host', 'rm', '-f', sf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                else:
                    Path(sf).unlink(missing_ok=True)
            except Exception:
                pass

    def _handle_line(self, line):
        # stream_linux.py prints status lines; try to infer phases
        low = line.lower()
        with self._lock:
            if 'waiting for powered goggles' in low or 'waiting for goggles' in low:
                self._state['phase'] = 'waiting'
                self._state['problem'] = {'code': 'unplugged', 'message': line}
            elif 'connected' in low and self._state.get('phase') in ('checking', 'waiting', 'idle'):
                self._state['phase'] = 'connecting'
                self._state['problem'] = None
            elif 'ready' in low or 'virtual flight' in low:
                self._state['phase'] = 'ready'
            elif 'streaming' in low or 'fps' in low and 'frame' in low:
                self._state['phase'] = 'streaming'
            elif 'error' in low or 'traceback' in low or 'failed' in low:
                self._state['phase'] = 'error'
                self._state['problem'] = {'code': 'other', 'message': line[:300]}
            # Try parse JSONL-like fragments if present
            if line.startswith('{') and '"event"' in line:
                try:
                    row = json.loads(line)
                    ev = row.get('event')
                    if ev == 'ready':
                        self._state['phase'] = 'ready'
                        self._device = {'model': row.get('model', 'Goggles'), 'identity': row.get('identity', ''), 'build': '', 'version': None, 'tested': True, 'tested_versions': []}
                    elif ev == 'streaming':
                        self._state['phase'] = 'streaming'
                    elif ev == 'stats':
                        self._state['stats'] = {
                            'fps': row.get('fps', 0),
                            'send_ms_p95': row.get('send_ms_p95', 0),
                            'frame_bytes_max': row.get('frame_bytes_max', 0),
                        }
                    elif ev == 'oversize_frame':
                        self._state['oversize'] = int(self._state.get('oversize', 0)) + 1
                    elif ev == 'waiting':
                        self._state['phase'] = 'waiting'
                        self._state['problem'] = {'code': 'unplugged', 'message': row.get('message', '')}
                    elif ev == 'error':
                        self._state['phase'] = 'error'
                        self._state['problem'] = {'code': 'other', 'message': row.get('message', 'error')}
                except Exception:
                    pass

    def stop(self):
        with self._lock:
            proc = self._proc
            sf = self._stop_file
            if sf:
                try:
                    if os.environ.get('FLATPAK_ID'):
                        subprocess.run(['flatpak-spawn', '--host', 'sh', '-c', 'printf stop > "$1"', '--', sf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                    else:
                        Path(sf).write_text('stop\n', encoding='utf-8')
                except Exception:
                    pass
            if proc and proc.poll() is None:
                try:
                    proc.send_signal(signal.SIGINT)
                except Exception:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
        return {'ok': True}

    def open_link(self, name):
        if name == 'logs':
            d = log_dir()
            d.mkdir(parents=True, exist_ok=True)
            try:
                subprocess.run(['xdg-open', str(d)], check=False)
            except Exception:
                pass
        elif name == 'github':
            webbrowser.open('https://github.com/Ammaar-Alam/g2-bridge')
        elif name == 'report':
            webbrowser.open('https://github.com/Ammaar-Alam/g2-bridge/issues')
        elif name == 'driver':
            webbrowser.open('https://www.dji.com/downloads')
        return {'ok': True}

    def diagnostics(self):
        with self._lock:
            st = dict(self._state)
            opts = dict(self._options)
        report = [
            'Goggles Bridge (Linux)',
            f'platform={sys.platform}',
            f'options={json.dumps(opts, ensure_ascii=False)}',
            f'state={json.dumps(st, ensure_ascii=False)}',
            f'log={st.get("log")}',
        ]
        txt = '\n'.join(report)
        try:
            p = subprocess.Popen(['wl-copy'], stdin=subprocess.PIPE)
            p.communicate(input=txt.encode('utf-8'), timeout=3)
        except Exception:
            try:
                p = subprocess.Popen(['xclip', '-selection', 'clipboard'], stdin=subprocess.PIPE)
                p.communicate(input=txt.encode('utf-8'), timeout=3)
            except Exception:
                pass
        return txt

    def check_update(self):
        return {'version': None}

    def install_update(self):
        return {'error': 'Updates not supported in Linux build'}


class ApiBridge:
    def __init__(self, backend):
        self.backend = backend

    def snapshot(self): return self.backend.snapshot()
    def set_options(self, options=None, **kwargs): return self.backend.set_options(options, **kwargs)
    def start(self): return self.backend.start()
    def stop(self): return self.backend.stop()
    def finish_setup(self): return self.backend.finish_setup()
    def open_link(self, name): return self.backend.open_link(name)
    def diagnostics(self): return self.backend.diagnostics()
    def check_update(self): return self.backend.check_update()
    def install_update(self): return self.backend.install_update()


def run_webkit():
    import gi
    try:
        gi.require_version('Gtk', '4.0')
        gi.require_version('WebKit', '6.0')
        from gi.repository import Gtk, WebKit, GLib
        gtk4 = True
    except Exception:
        gi.require_version('Gtk', '3.0')
        gi.require_version('WebKit2', '4.1')
        from gi.repository import Gtk, WebKit2 as WebKit, GLib
        gtk4 = False

    backend = LinuxDesktopBackend()
    api = ApiBridge(backend)

    class Bridge:
        # Exposed to JS via message handler; simple JSON-RPC-ish
        def __init__(self, webview):
            self.webview = webview

    if gtk4:
        app = Gtk.Application(application_id='io.github.sevara.G2BridgeDesktop')
    else:
        app = Gtk.Application(application_id='io.github.sevara.G2BridgeDesktop')

    def on_activate(app):
        if gtk4:
            win = Gtk.ApplicationWindow(application=app)
            win.set_default_size(1120, 740)
            win.set_title('Goggles Bridge')
            webview = WebKit.WebView()
            win.set_child(webview)
        else:
            win = Gtk.ApplicationWindow(application=app)
            win.set_default_size(1120, 740)
            win.set_title('Goggles Bridge')
            webview = WebKit.WebView()
            win.add(webview)

        # Inject a JS shim that provides window.pywebview.api calling back via prompt
        shim = r"""
        (function(){
          function call(method, args){
            try {
              const payload = JSON.stringify({method: method, args: args || []});
              const res = window.prompt('__G2_API__:'+payload);
              return JSON.parse(res || '{}');
            } catch(e){ return {error: String(e)}; }
          }
          const api = {
            snapshot: async ()=>call('snapshot', []),
            set_options: async (options)=>call('set_options', [options||{}]),
            start: async ()=>call('start', []),
            stop: async ()=>call('stop', []),
            finish_setup: async ()=>call('finish_setup', []),
            open_link: async (name)=>call('open_link', [name]),
            diagnostics: async ()=>call('diagnostics', []),
            check_update: async ()=>call('check_update', []),
            install_update: async ()=>call('install_update', []),
          };
          window.pywebview = { api: api };
          window.dispatchEvent(new Event('pywebviewready'));
        })();
        """

        def handle_prompt(wv, dialog, *rest):
            try:
                if gtk4:
                    msg = dialog.get_message()
                else:
                    msg = dialog.get_message()
                if not msg.startswith('__G2_API__:'):
                    return False
                payload = json.loads(msg[len('__G2_API__:'):])
                method = payload.get('method')
                args = payload.get('args') or []
                fn = getattr(api, method, None)
                result = {'error': 'unknown method'} if fn is None else fn(*args)
                resp = json.dumps(result)
                if gtk4:
                    dialog.prompt_set_text(resp)
                else:
                    dialog.set_text(resp)
                dialog.response(WebKit.ScriptDialogResponse.OK if hasattr(WebKit, 'ScriptDialogResponse') else 0)
                return True
            except Exception as e:
                try:
                    resp = json.dumps({'error': str(e)})
                    if gtk4:
                        dialog.prompt_set_text(resp)
                    else:
                        dialog.set_text(resp)
                    dialog.response(WebKit.ScriptDialogResponse.OK if hasattr(WebKit, 'ScriptDialogResponse') else 0)
                except Exception:
                    pass
                return True

        if gtk4:
            # GTK4/WebKit6 script dialogs differ; fallback to simpler approach: use user content manager message handler not trivial here
            # but try 'script-dialog' signal
            try:
                webview.connect('script-dialog', lambda wv, d: handle_prompt(wv, d))
            except Exception:
                pass
            content = webview.get_user_content_manager()
            try:
                content.add_script(WebKit.UserScript(shim, WebKit.UserContentInjectedFrames.ALL_FRAMES, WebKit.UserScriptInjectionTime.START, None, None))
            except Exception:
                pass
            webview.load_uri((UI / 'index.html').resolve().as_uri())
            win.present()
        else:
            webview.connect('script-dialog', lambda wv, d: handle_prompt(wv, d))
            content = webview.get_user_content_manager()
            content.add_script(WebKit.UserScript(shim, WebKit.UserContentInjectedFrames.ALL_FRAMES, WebKit.UserScriptInjectionTime.START, None, None))
            webview.load_uri((UI / 'index.html').resolve().as_uri())
            win.show_all()

        backend._quit = lambda: GLib.idle_add(lambda: (backend.stop(), app.quit() if not gtk4 else win.close(), False)[-1])

    app.connect('activate', on_activate)
    app.run(None)


def main():
    try:
        run_webkit()
    except Exception as e:
        print(f'Failed to start desktop UI: {e}', file=sys.stderr)
        # Fallback to existing GTK app
        try:
            os.execv(sys.executable, [sys.executable, str(ROOT / 'scripts' / 'g2_bridge_app.py')])
        except Exception:
            raise


if __name__ == '__main__':
    main()
