#!/usr/bin/env python3
import json
import math
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STREAM_SCRIPT = ROOT / 'scripts' / 'stream_linux.py'

BITRATE_CHOICES = ['8', '10', '12', '14', '16', '18', '20', '24', '30', '32', '40']
FPS_CHOICES = ['60', '75', '90', '100']
KEYFRAME_CHOICES = ['1', '3']
PRESET_CHOICES = ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium']
ENCODER_CHOICES = ['auto', 'libx264', 'vaapi', 'vulkan']
ROTATION_CHOICES = ['none', '90', '180', '270']


def config_path():
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(Path.home(), '.config')
    return Path(base) / 'g2-bridge' / 'settings.json'


def default_settings():
    return {
        'rotation': '270',
        'bitrate': '40',
        'fps': '100',
        'keyframe_seconds': '3',
        'preset': 'ultrafast',
        'encoder': 'libx264',
        'screen_off': False,
        'show_log': True,
        'quick_start': False,
        'settings_visible': True,
    }


def load_settings():
    s = default_settings()
    try:
        data = json.loads(config_path().read_text(encoding='utf-8'))
        if isinstance(data, dict):
            s.update({k: data[k] for k in s if k in data})
    except Exception:
        pass
    if str(s.get('rotation')) not in ROTATION_CHOICES:
        s['rotation'] = '270'
    if str(s.get('bitrate')) not in BITRATE_CHOICES:
        s['bitrate'] = '40'
    if str(s.get('fps')) not in FPS_CHOICES:
        s['fps'] = '100'
    if str(s.get('keyframe_seconds')) not in KEYFRAME_CHOICES:
        s['keyframe_seconds'] = '3'
    if str(s.get('preset')) not in PRESET_CHOICES:
        s['preset'] = 'ultrafast'
    if str(s.get('encoder')) not in ENCODER_CHOICES:
        s['encoder'] = 'libx264'
    for k in ('screen_off', 'show_log', 'quick_start', 'settings_visible'):
        s[k] = bool(s.get(k, False)) if k != 'show_log' and k != 'settings_visible' else bool(s.get(k, True))
    s['quick_start'] = bool(s.get('quick_start', False))
    return s


def save_settings(settings):
    p = config_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    except Exception:
        pass


def get_gtk():
    try:
        import gi
        gi.require_version('Gtk', '4.0')
        gi.require_version('Adw', '1')
        from gi.repository import Adw, Gio, GLib, Gtk, Gdk
        return 4, (Adw, Gio, GLib, Gtk, Gdk)
    except Exception:
        pass
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gio, GLib, Gtk, Gdk
        return 3, (None, Gio, GLib, Gtk, Gdk)
    except Exception as e:
        print(f'GTK not available: {e}', file=sys.stderr)
        return 0, None


def _runtime_dir():
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


def build_cmd(settings):
    rotation = str(settings.get('rotation', '270'))
    bitrate = str(settings.get('bitrate', '40'))
    fps = str(settings.get('fps', '100'))
    keyframe = str(settings.get('keyframe_seconds', '3'))
    preset = str(settings.get('preset', 'ultrafast'))
    encoder = str(settings.get('encoder', 'libx264'))
    if encoder not in ENCODER_CHOICES:
        encoder = 'libx264'
    screen_off = bool(settings.get('screen_off'))

    args = ['--source', 'desktop', '--desktop-capture', 'kmsgrab',
            '--encoder', encoder, '--preset', preset,
            '--kmsgrab-rotate', rotation if rotation in ROTATION_CHOICES else '270',
            '--gpu-filters', 'off',
            '--fps', fps, '--capture-fps', fps,
            '--bitrate-mbps', bitrate,
            '--keyframe-seconds', keyframe]
    if screen_off:
        args += ['--screen-off-on-connect']
    extra = os.environ.get('G2_BRIDGE_EXTRA_ARGS', '').strip()
    if extra:
        args += extra.split()

    if os.environ.get('FLATPAK_ID'):
        try:
            _deploy_runtime()
        except Exception as e:
            print(f'g2-bridge: runtime deploy warning: {e}', file=sys.stderr)
        runtime = _runtime_dir()
        host_python = os.environ.get('G2_BRIDGE_HOST_PYTHON', 'python3')
        host_script = str(runtime / 'scripts' / 'stream_linux.py')
        pp = _runtime_pythonpath(runtime)
        path_env = os.environ.get('PATH', '/usr/bin:/bin')
        bin_dir = runtime / 'bin'
        if bin_dir.exists():
            path_env = f"{bin_dir}:{path_env}"
        ffmpeg_arg = ['--ffmpeg', os.environ.get('G2_BRIDGE_HOST_FFMPEG', '/usr/bin/ffmpeg')]
        return ['flatpak-spawn', '--host', 'pkexec', 'env', f'PYTHONPATH={pp}', f'PATH={path_env}', host_python, host_script] + args + ffmpeg_arg
    return [sys.executable, str(STREAM_SCRIPT)] + args


CSS = r"""
window, .background { background-color: #000000; color: #f2f4f8; }
headerbar { background: #000000; color: #f2f4f8; border-bottom: none; box-shadow: none; min-height: 38px; }
.card { background-color: #000000; border-radius: 18px; padding: 20px; border: 1px solid rgba(255,255,255,0.35); }
.settings-card { background-color: #000000; border-radius: 14px; padding: 10px; border: 1px solid rgba(255,255,255,0.35); }
.group-card { background-color: #000000; border-radius: 12px; border: 1px solid rgba(255,255,255,0.35); }
.group-row { padding: 6px 10px; }
.group-sep { background: rgba(255,255,255,0.35); min-height: 1px; }
.title { font-size: 28px; font-weight: 700; }
.subtitle { font-size: 14px; color: #c6ccd6; }
.muted { color: #97a1ae; }
.section-title { font-size: 12px; font-weight: 600; color: #97a1ae; margin-top: 2px; }
.accent-btn { background: #2a84ff; color: #ffffff; border-radius: 12px; min-height: 42px; font-weight: 600; padding: 0 18px; border: 1px solid rgba(255,255,255,0.35); }
.accent-btn:hover { background: #1f6fe0; }
.stop-btn { background: #000000; color: #f2f4f8; border-radius: 12px; min-height: 42px; font-weight: 600; padding: 0 18px; border: 1px solid rgba(255,255,255,0.35); }
.stop-btn:hover { background: #111111; }
.link-btn { background: transparent; color: #7db6ff; border-radius: 8px; padding: 2px 6px; border: 1px solid transparent; }
.link-btn:hover { background: rgba(42,132,255,0.14); border: 1px solid rgba(255,255,255,0.35); }
.check-card { background: #000000; border-radius: 12px; border: 1px solid rgba(255,255,255,0.35); padding: 10px 12px; }
.log-view text, textview text { background-color: #000000; color: #dfe6f0; }
scrolledwindow, viewport { background-color: #000000; }
frame, .frame { border: 1px solid rgba(255,255,255,0.35); }

/* Rounded AMOLED popovers/menus */
popover, popover.background { background: transparent; }
popover > contents, popover > arrow {
  background-color: #000000; color: #f2f4f8;
  border: none;
  border-radius: 14px; padding: 6px;
}
popover.background > contents { background-color: #000000; border-radius: 14px; border: none; }
popover listview, popover list, popover .view { background: transparent; color: #f2f4f8; }
popover row, popover modelbutton, popover .item { border-radius: 10px; padding: 6px 10px; color: #f2f4f8; }
popover row:selected, popover row:hover, popover modelbutton:hover { background-color: #111111; }
dropdown > button {
  background-color: #000000; color: #f2f4f8;
  border: 1px solid rgba(255,255,255,0.35);
  border-radius: 10px; padding: 2px 8px; min-height: 30px;
}
dropdown > button:hover { background-color: #111111; }
combobox button, combobox window menu, combobox window {
  background-color: #000000; color: #f2f4f8;
  border: none; border-radius: 12px;
}
menu, .menu, .context-menu {
  background-color: #000000; color: #f2f4f8;
  border: none;
  border-radius: 14px; padding: 6px;
}
menuitem { border-radius: 10px; padding: 6px 10px; }
menuitem:hover { background-color: #111111; }
separator { background-color: rgba(255,255,255,0.35); min-height: 1px; min-width: 1px; }
switch { border-radius: 999px; }
"""


def draw_scene(area, cr, width, height, running, version):
    cr.save()
    sx = width / 600.0
    sy = height / 220.0
    s = min(sx, sy)
    cr.translate((width - 600*s)/2, (height - 220*s)/2)
    cr.scale(s, s)

    def rr(x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x+w-r, y+r, r, -math.pi/2, 0)
        cr.arc(x+w-r, y+h-r, r, 0, math.pi/2)
        cr.arc(x+r, y+h-r, r, math.pi/2, math.pi)
        cr.arc(x+r, y+r, r, math.pi, 3*math.pi/2)
        cr.close_path()

    # monitor
    cr.set_source_rgb(0, 0, 0)
    rr(40, 24, 220, 146, 12); cr.fill_preserve()
    cr.set_source_rgba(1,1,1,0.35); cr.set_line_width(1.5); cr.stroke()
    # screen
    cr.set_source_rgb(0.05, 0.08, 0.12)
    rr(50, 34, 200, 126, 6); cr.fill_preserve()
    cr.set_source_rgba(1,1,1,0.25); cr.stroke()
    cr.set_source_rgba(1,1,1,0.22); cr.set_line_width(4)
    cr.move_to(66, 62); cr.line_to(150, 62); cr.stroke()
    cr.move_to(66, 78); cr.line_to(210, 78); cr.stroke()
    cr.move_to(66, 94); cr.line_to(120, 94); cr.stroke()
    cr.set_source_rgba(1,1,1,0.18)
    rr(120, 88, 110, 60, 6); cr.stroke()
    # base
    cr.set_source_rgb(0,0,0)
    rr(16, 172, 268, 12, 6); cr.fill_preserve()
    cr.set_source_rgba(1,1,1,0.35); cr.set_line_width(1.5); cr.stroke()
    # cable
    cr.set_line_width(3)
    cr.set_source_rgba(0.165, 0.518, 1.0, 1.0) if running else cr.set_source_rgba(1,1,1,0.35)
    cr.move_to(284, 178); cr.curve_to(340, 178, 340, 112, 384, 112); cr.stroke()
    # plug
    cr.set_source_rgb(0,0,0); rr(384,104,16,16,4); cr.fill_preserve()
    cr.set_source_rgba(0.165,0.518,1.0,1.0) if running else cr.set_source_rgba(1,1,1,0.35)
    cr.set_line_width(1.5); cr.stroke()
    # goggles
    cr.set_source_rgb(0,0,0)
    cr.new_path()
    cr.move_to(398, 92); cr.curve_to(398,72,412,59,431,59); cr.line_to(551,59)
    cr.curve_to(570,59,584,72,584,92); cr.line_to(584,119)
    cr.curve_to(584,142,567,159,544,159); cr.curve_to(531,159,521,152,514,142)
    cr.curve_to(507,132,491,126,491,126); cr.curve_to(491,126,475,132,468,142)
    cr.curve_to(461,152,451,159,438,159); cr.curve_to(415,159,398,142,398,119)
    cr.close_path(); cr.fill_preserve()
    cr.set_source_rgba(1,1,1,0.35); cr.set_line_width(1.5); cr.stroke()
    for cx in (451, 530):
        cr.set_source_rgb(0,0,0); cr.arc(cx,106,26,0,2*math.pi); cr.fill()
        if running:
            cr.set_source_rgba(0.165,0.518,1.0,0.2); cr.arc(cx,106,22,0,2*math.pi); cr.fill()
        cr.set_source_rgba(1,1,1,0.35); cr.arc(cx,106,26,0,2*math.pi); cr.stroke()
    cr.restore()


def main():
    version, mods = get_gtk()
    if version == 0:
        os.execv(sys.executable, [sys.executable, str(STREAM_SCRIPT)] + sys.argv[1:])

    app_id = os.environ.get('FLATPAK_ID') or 'io.github.sevara.G2Bridge'
    if version == 4:
        Adw, Gio, GLib, Gtk, Gdk = mods
        app = Adw.Application(application_id=app_id, flags=Gio.ApplicationFlags.FLAGS_NONE)
    else:
        _, Gio, GLib, Gtk, Gdk = mods
        Adw = None
        app = Gtk.Application(application_id=app_id, flags=Gio.ApplicationFlags.FLAGS_NONE)

    state = {'proc': None, 'settings': load_settings(), 'stop_file': None, 'running_ui': False}

    def append_log(buf, text_view, text):
        def _do():
            end = buf.get_end_iter()
            buf.insert(end, text)
            if buf.get_line_count() > 2000:
                start = buf.get_start_iter()
                cut = buf.get_iter_at_line(200)
                buf.delete(start, cut)
            mark = buf.create_mark(None, buf.get_end_iter(), False)
            text_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
            buf.delete_mark(mark)
            return False
        GLib.idle_add(_do)

    def apply_css():
        try:
            provider = Gtk.CssProvider()
            provider.load_from_data(CSS.encode('utf-8'))
            if version == 4:
                display = Gdk.Display.get_default()
                if display:
                    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            else:
                screen = Gdk.Screen.get_default()
                if screen:
                    Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except Exception:
            pass

    def on_activate(app):
        apply_css()
        s = state['settings']

        if version == 4:
            win = Adw.ApplicationWindow(application=app)
            win.set_title('Goggles Bridge')
            win.set_default_size(980, 620)
            try:
                win.set_resizable(True)
            except Exception:
                pass
            root = Adw.ToolbarView()
            header = Adw.HeaderBar()
            title = Adw.WindowTitle(title='Goggles Bridge', subtitle='')
            header.set_title_widget(title)
            root.add_top_bar(header)
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=8, margin_bottom=8, margin_start=10, margin_end=10)
            root.set_content(outer)
            win.set_content(root)
        else:
            win = Gtk.ApplicationWindow(application=app)
            win.set_title('Goggles Bridge')
            win.set_default_size(980, 620)
            try:
                win.set_resizable(True)
            except Exception:
                pass
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            outer.set_margin_top(8); outer.set_margin_bottom(8); outer.set_margin_start(10); outer.set_margin_end(10)
            win.add(outer)

        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        main_box.set_vexpand(True)
        outer.append(main_box)

        # Left stage (restored layout)
        stage = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        try: stage.add_css_class('card')
        except Exception: pass
        stage.set_hexpand(True)
        main_box.append(stage)

        scene = Gtk.DrawingArea()
        scene.set_content_width(560); scene.set_content_height(220)
        if version == 4:
            scene.set_draw_func(lambda area, cr, w, h: draw_scene(area, cr, w, h, state['running_ui'], version))
        else:
            scene.connect('draw', lambda area, cr: draw_scene(area, cr, area.get_allocated_width(), area.get_allocated_height(), state['running_ui'], version))
        stage.append(scene)

        headline = Gtk.Label(label='Ready to stream', xalign=0.5)
        subline = Gtk.Label(label='Put your goggles in More → DJI Virtual Flight, then start streaming.', xalign=0.5, wrap=True, justify=Gtk.Justification.CENTER)
        try:
            headline.add_css_class('title'); subline.add_css_class('subtitle')
        except Exception: pass
        subline.set_max_width_chars(52)
        stage.append(headline); stage.append(subline)

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        action_row.set_halign(Gtk.Align.CENTER)
        start_btn = Gtk.Button(label='Start streaming')
        stop_btn = Gtk.Button(label='Stop')
        stop_btn.set_sensitive(False)
        try:
            start_btn.add_css_class('accent-btn'); stop_btn.add_css_class('stop-btn')
            start_btn.set_size_request(190,44); stop_btn.set_size_request(120,44)
        except Exception: pass
        action_row.append(start_btn); action_row.append(stop_btn)
        stage.append(action_row)

        profile_lbl = Gtk.Label(label='', xalign=0.5, wrap=True)
        try: profile_lbl.add_css_class('muted')
        except Exception: pass
        stage.append(profile_lbl)

        checks = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        checks.set_margin_top(8)
        def make_check(title, value):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            try: box.add_css_class('check-card')
            except Exception: pass
            box.set_hexpand(True)
            t = Gtk.Label(label=title, xalign=0)
            v = Gtk.Label(label=value, xalign=0)
            try: t.add_css_class('muted')
            except Exception: pass
            box.append(t); box.append(v)
            checks.append(box)
            return v
        chk_capture = make_check('Capture', 'kmsgrab (DRM)')
        chk_route = make_check('Route', 'USB PC (V1)')
        chk_state = make_check('Status', 'Idle')
        stage.append(checks)

        # Bottom links in left/stage window
        bottom_links = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bottom_links.set_margin_top(8)
        spacer_l = Gtk.Label(label=''); spacer_l.set_hexpand(True); bottom_links.append(spacer_l)
        logs_dir = Path(os.environ.get('XDG_STATE_HOME') or (Path.home()/'.local/state')) / 'g2-bridge' / 'logs'
        for text, target in (('Open logs', ['xdg-open', str(logs_dir)]), ('GitHub', ['xdg-open', 'https://github.com/sevara-wind/g2-bridge-linux'])):
            b = Gtk.Button(label=text)
            try:
                b.add_css_class('link-btn'); b.add_css_class('flat')
            except Exception:
                pass
            b.connect('clicked', lambda _, cmd=target: (subprocess.Popen(cmd) if cmd else None))
            bottom_links.append(b)
        spacer_r = Gtk.Label(label=''); spacer_r.set_hexpand(True); bottom_links.append(spacer_r)
        stage.append(bottom_links)

        # Right settings (no scroll)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        try: right.set_size_request(360, -1)
        except Exception: pass
        main_box.append(right)

        settings_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        try: settings_card.add_css_class('settings-card')
        except Exception: pass
        right.append(settings_card)

        def make_combo(values, labels, selected_value):
            idx = values.index(str(selected_value)) if str(selected_value) in values else 0
            if version == 4:
                w = Gtk.DropDown(model=Gtk.StringList.new(labels), selected=idx)
            else:
                w = Gtk.ComboBoxText()
                for l in labels: w.append_text(l)
                w.set_active(idx)
            return w
        def get_selected(combo, values):
            idx = combo.get_selected() if version == 4 else combo.get_active()
            if idx is None or idx < 0: idx = 0
            return values[max(0, min(idx, len(values)-1))]

        basic_lbl = Gtk.Label(label='Basic', xalign=0)
        try: basic_lbl.add_css_class('section-title')
        except Exception: pass
        settings_card.append(basic_lbl)
        basic_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        try: basic_group.add_css_class('group-card')
        except Exception: pass
        settings_card.append(basic_group)

        adv_lbl = Gtk.Label(label='Advanced', xalign=0)
        try: adv_lbl.add_css_class('section-title')
        except Exception: pass
        adv_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        try: adv_group.add_css_class('group-card')
        except Exception: pass

        controls = {}

        def add_group_row(group, label_text, widget, sep=True):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            try: row.add_css_class('group-row')
            except Exception: pass
            lbl = Gtk.Label(label=label_text, xalign=0)
            lbl.set_hexpand(True)
            row.append(lbl); row.append(widget)
            group.append(row)
            if sep:
                line = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                try: line.add_css_class('group-sep')
                except Exception: pass
                group.append(line)
            return row

        rot_combo = make_combo(ROTATION_CHOICES, ['None','90°','180°','270°'], s.get('rotation'))
        controls['rotation'] = rot_combo
        add_group_row(basic_group, 'Rotation', rot_combo)

        fps_combo = make_combo(FPS_CHOICES, [f'{v} fps' for v in FPS_CHOICES], s.get('fps'))
        controls['fps'] = fps_combo
        add_group_row(basic_group, 'Frame rate', fps_combo)

        br_combo = make_combo(BITRATE_CHOICES, [f'{v} Mbps' for v in BITRATE_CHOICES], s.get('bitrate'))
        controls['bitrate'] = br_combo
        add_group_row(basic_group, 'Bitrate', br_combo)

        kf_combo = make_combo(KEYFRAME_CHOICES, ['1s','3s'], s.get('keyframe_seconds'))
        controls['keyframe_seconds'] = kf_combo
        add_group_row(basic_group, 'Keyframe', kf_combo)

        enc_combo = make_combo(ENCODER_CHOICES, ['Auto', 'libx264', 'VAAPI', 'Vulkan'], s.get('encoder'))
        controls['encoder'] = enc_combo
        add_group_row(basic_group, 'Encoder', enc_combo)

        screen_off_sw = Gtk.Switch(); screen_off_sw.set_active(bool(s.get('screen_off')))
        controls['screen_off'] = screen_off_sw
        add_group_row(basic_group, 'Dim device screen', screen_off_sw, sep=False)

        settings_card.append(adv_lbl)
        settings_card.append(adv_group)

        preset_combo = make_combo(PRESET_CHOICES, PRESET_CHOICES, s.get('preset'))
        controls['preset'] = preset_combo
        add_group_row(adv_group, 'x264 preset', preset_combo)

        show_log_sw = Gtk.Switch(); show_log_sw.set_active(bool(s.get('show_log', True)))
        controls['show_log'] = show_log_sw
        add_group_row(adv_group, 'Show log', show_log_sw)

        quick_sw = Gtk.Switch(); quick_sw.set_active(bool(s.get('quick_start', False)))
        controls['quick_start'] = quick_sw
        add_group_row(adv_group, 'Quick start', quick_sw, sep=False)

        # Log card
        log_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        try: log_card.add_css_class('settings-card')
        except Exception: pass
        log_card.set_vexpand(True)
        right.append(log_card)
        log_title = Gtk.Label(label='Log', xalign=0)
        try: log_title.add_css_class('section-title')
        except Exception: pass
        log_card.append(log_title)
        scrolled = Gtk.ScrolledWindow(); scrolled.set_vexpand(True); scrolled.set_hexpand(True)
        text_view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        try: text_view.add_css_class('log-view')
        except Exception: pass
        buf = text_view.get_buffer()
        if version == 4: scrolled.set_child(text_view)
        else: scrolled.add(text_view)
        log_card.append(scrolled)

        def set_log_visible(v): log_card.set_visible(v)

        def current_settings():
            return {
                'rotation': get_selected(rot_combo, ROTATION_CHOICES),
                'fps': get_selected(fps_combo, FPS_CHOICES),
                'bitrate': get_selected(br_combo, BITRATE_CHOICES),
                'encoder': get_selected(enc_combo, ENCODER_CHOICES),
                'keyframe_seconds': get_selected(kf_combo, KEYFRAME_CHOICES),
                'preset': get_selected(preset_combo, PRESET_CHOICES),
                'screen_off': screen_off_sw.get_active(),
                'show_log': show_log_sw.get_active(),
                'quick_start': quick_sw.get_active(),
                'settings_visible': True,
            }

        def persist_current():
            st = current_settings()
            state['settings'] = st
            save_settings(st)
            update_profile_label(st)

        def update_profile_label(st=None):
            st = st or state['settings']
            enc = st.get('encoder', 'libx264')
            enc_label = {'auto': 'Auto', 'libx264': 'libx264', 'vaapi': 'VAAPI', 'vulkan': 'Vulkan'}.get(enc, enc)
            profile_lbl.set_text(
                f"kmsgrab · {enc_label} {st['preset']} · {st['fps']} fps · {st['bitrate']} Mbps · keyframe {st['keyframe_seconds']}s"
            )

        def redraw_scene():
            try: scene.queue_draw()
            except Exception: pass

        def reader_thread(proc):
            try:
                for line in iter(proc.stdout.readline, ''):
                    if not line: break
                    append_log(buf, text_view, line)
            except Exception:
                pass
            try: proc.wait()
            except Exception: pass
            def done():
                sf = state.get('stop_file')
                if sf:
                    try:
                        if os.environ.get('FLATPAK_ID'):
                            subprocess.run(['flatpak-spawn','--host','rm','-f',sf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                        else:
                            Path(sf).unlink(missing_ok=True)
                    except Exception: pass
                state['stop_file'] = None; state['proc'] = None; state['running_ui'] = False
                start_btn.set_sensitive(True); stop_btn.set_sensitive(False)
                headline.set_text('Stream stopped')
                subline.set_text('Put your goggles in More → DJI Virtual Flight, then start streaming.')
                chk_state.set_text('Idle'); redraw_scene()
                return False
            GLib.idle_add(done)

        def start_stream(_btn=None):
            if state['proc'] is not None: return
            persist_current()
            st = state['settings']
            in_flatpak = bool(os.environ.get('FLATPAK_ID'))
            stop_name = f'g2-bridge-stop-{os.getpid()}-{threading.get_ident()}'
            if in_flatpak:
                stop_file = f'/tmp/{stop_name}'
                try:
                    subprocess.run(['flatpak-spawn','--host','rm','-f',stop_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                except Exception: pass
            else:
                stop_dir = Path(os.environ.get('XDG_RUNTIME_DIR') or os.path.join(Path.home(), '.cache'))
                try: stop_dir.mkdir(parents=True, exist_ok=True)
                except Exception: stop_dir = Path('/tmp')
                stop_file = str(stop_dir / stop_name)
                try: Path(stop_file).unlink(missing_ok=True)
                except Exception: pass
            state['stop_file'] = stop_file
            cmd = build_cmd(st) + ['--stop-file', stop_file]
            append_log(buf, text_view, 'Starting: ' + ' '.join(cmd) + '\n')
            headline.set_text('Starting…')
            subline.set_text('Connecting to goggles and launching capture.')
            chk_state.set_text('Starting')
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            except Exception as e:
                append_log(buf, text_view, f'Launch error: {e}\n')
                headline.set_text('Launch error'); subline.set_text(str(e)); chk_state.set_text('Error')
                state['stop_file'] = None
                return
            state['proc'] = proc; state['running_ui'] = True
            start_btn.set_sensitive(False); stop_btn.set_sensitive(True)
            headline.set_text('Streaming')
            subline.set_text(f"{st['bitrate']} Mbps · rotation {st['rotation']}° · {st['fps']} fps · keyframe {st['keyframe_seconds']}s")
            chk_state.set_text('Running'); redraw_scene()
            t = threading.Thread(target=reader_thread, args=(proc,), daemon=True)
            t.start()

        def stop_stream(_btn=None):
            proc = state['proc']
            if proc is None: return
            headline.set_text('Stopping…'); subline.set_text('Stopping capture and restoring screen state.')
            chk_state.set_text('Stopping')
            sf = state.get('stop_file')
            if sf:
                if os.environ.get('FLATPAK_ID'):
                    try:
                        subprocess.run(['flatpak-spawn','--host','sh','-c','printf stop > "$1"','--',sf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                    except Exception: pass
                else:
                    try: Path(sf).write_text('stop\n', encoding='utf-8')
                    except Exception: pass
            try: proc.send_signal(signal.SIGINT)
            except Exception:
                try: proc.terminate()
                except Exception: pass

        start_btn.connect('clicked', start_stream)
        stop_btn.connect('clicked', stop_stream)

        for combo in (rot_combo, fps_combo, br_combo, kf_combo, enc_combo, preset_combo):
            if version == 4: combo.connect('notify::selected', lambda *_: persist_current())
            else: combo.connect('changed', lambda *_: persist_current())
        for sw in (screen_off_sw, show_log_sw, quick_sw):
            sw.connect('notify::active', lambda *_: (set_log_visible(show_log_sw.get_active()), persist_current()))

        update_profile_label(s)
        set_log_visible(show_log_sw.get_active())

        if bool(s.get('quick_start')) and os.environ.get('G2_NO_QUICK_START') != '1':
            GLib.idle_add(lambda: (start_stream(), False)[1])

        if version == 4:
            win.connect('close-request', lambda *_: (stop_stream(), False)[1])
            win.present()
        else:
            win.connect('destroy', lambda *_: (stop_stream(), app.quit()))
            win.show_all()

    app.connect('activate', on_activate)
    app.run(None)


if __name__ == '__main__':
    main()
