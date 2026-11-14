#!/usr/bin/env python3
import argparse
import signal
import sys

try:
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk, Gdk, GLib
    GTK4 = True
except Exception:
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, Gdk, GLib
        GTK4 = False
    except Exception as e:
        print(f'GTK not available: {e}', file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=0, help='Auto-close after N seconds (0 = until closed/killed)')
    args = ap.parse_args()

    if GTK4:
        app = Gtk.Application(application_id='io.github.sevara_wind.G2Bridge.BlackScreen')

        def on_activate(app):
            win = Gtk.ApplicationWindow(application=app)
            win.set_title('G2 Bridge Black Screen')
            win.set_decorated(False)
            provider = Gtk.CssProvider()
            provider.load_from_data(b'window, .background { background-color: #000000; }')
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            try:
                win.fullscreen()
            except Exception:
                pass
            # Try to present and stay on top where supported
            win.present()
            try:
                win.set_keep_above(False)
            except Exception:
                pass
            if args.seconds and args.seconds > 0:
                GLib.timeout_add(int(args.seconds * 1000), lambda: (win.close(), False)[1])
        app.connect('activate', on_activate)
        # handle SIGTERM/SIGINT
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (app.quit(), False)[1])
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: (app.quit(), False)[1])
        app.run([])
    else:
        win = Gtk.Window()
        win.set_title('G2 Bridge Black Screen')
        win.set_decorated(False)
        win.modify_bg(Gtk.StateType.NORMAL, Gdk.color_parse('#000000'))
        try:
            win.fullscreen()
        except Exception:
            try:
                win.maximize()
            except Exception:
                pass
        try:
            win.set_keep_above(False)
        except Exception:
            pass
        win.connect('destroy', Gtk.main_quit)
        win.show_all()
        if args.seconds and args.seconds > 0:
            GLib.timeout_add(int(args.seconds * 1000), lambda: (Gtk.main_quit(), False)[1])
        signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())
        signal.signal(signal.SIGINT, lambda *_: Gtk.main_quit())
        Gtk.main()


if __name__ == '__main__':
    main()
