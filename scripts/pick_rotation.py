#!/usr/bin/env python3
import sys

def pick():
    # Try GTK4, then GTK3, then zenity/kdialog fallback is handled by caller
    for gtk_ver in (4, 3):
        try:
            import gi
            gi.require_version('Gtk', f'{gtk_ver}.0')
            if gtk_ver == 4:
                gi.require_version('Adw', '1')
            from gi.repository import Gtk
            if gtk_ver == 4:
                from gi.repository import Adw
                app = Adw.Application(application_id='io.github.sevara_wind.G2Bridge.Picker')
                result = {'value': None, 'screen_off': '0'}
                def on_activate(app):
                    win = Adw.ApplicationWindow(application=app, title='G2 Bridge')
                    win.set_default_size(360, 280)
                    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                                  margin_top=20, margin_bottom=20, margin_start=20, margin_end=20)
                    label = Gtk.Label(label='Select screen rotation')
                    box.append(label)
                    group = None
                    buttons = []
                    options = [('No rotation', 'none'), ('90°', '90'), ('180°', '180'), ('270°', '270')]
                    for text, val in options:
                        rb = Gtk.CheckButton(label=text)
                        if group is None:
                            rb.set_active(True)
                            group = rb
                        else:
                            rb.set_group(group)
                        rb._val = val
                        buttons.append(rb)
                        box.append(rb)
                    screen_cb = Gtk.CheckButton(label='Turn off this device screen when goggles connect')
                    box.append(screen_cb)
                    btn = Gtk.Button(label='Start')
                    def on_click(_):
                        for b in buttons:
                            if b.get_active():
                                result['value'] = b._val
                                break
                        result['screen_off'] = '1' if screen_cb.get_active() else '0'
                        app.quit()
                    btn.connect('clicked', on_click)
                    box.append(btn)
                    win.set_content(box)
                    win.present()
                app.connect('activate', on_activate)
                app.run(None)
                return result
            else:
                from gi.repository import Gtk as Gtk3
                dialog = Gtk3.Dialog(title='G2 Bridge', flags=0)
                dialog.set_default_size(360, 280)
                dialog.add_button('Cancel', Gtk3.ResponseType.CANCEL)
                dialog.add_button('Start', Gtk3.ResponseType.OK)
                box = dialog.get_content_area()
                box.set_spacing(8)
                box.set_margin_top(12); box.set_margin_bottom(12)
                box.set_margin_start(12); box.set_margin_end(12)
                box.add(Gtk3.Label(label='Select screen rotation'))
                group = None
                buttons = []
                for text, val in [('No rotation','none'),('90°','90'),('180°','180'),('270°','270')]:
                    rb = Gtk3.RadioButton.new_with_label_from_widget(group, text)
                    if group is None:
                        group = rb
                        rb.set_active(True)
                    rb._val = val
                    buttons.append(rb)
                    box.add(rb)
                screen_cb = Gtk3.CheckButton(label='Turn off this device screen when goggles connect')
                box.add(screen_cb)
                dialog.show_all()
                resp = dialog.run()
                result = None
                if resp == Gtk3.ResponseType.OK:
                    val = None
                    for b in buttons:
                        if b.get_active():
                            val = b._val
                            break
                    result = {'value': val, 'screen_off': '1' if screen_cb.get_active() else '0'}
                dialog.destroy()
                return result
        except Exception:
            continue
    return None

if __name__ == '__main__':
    r = pick()
    if r is None:
        sys.exit(1)
    if isinstance(r, dict):
        print(r.get('value', 'none'))
        print(r.get('screen_off', '0'))
    else:
        print(r)
        print('0')
