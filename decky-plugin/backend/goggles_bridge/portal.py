"""Minimal xdg-desktop-portal ScreenCast client.

The portal owns the user consent dialog and cursor compositing.  It returns a
PipeWire node id which ``pipewiresrc`` can consume.  This is the capture path
that works on GNOME Wayland without root and includes the mouse pointer.

The implementation only needs the small, pure-Python ``jeepney`` D-Bus client
(``vendor/jeepney``); it does not depend on PyGObject or a running GTK app.
"""
from __future__ import annotations

import os
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'vendor'
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from jeepney import DBusAddress, HeaderFields, MatchRule, MessageType, new_method_call  # noqa: E402
from jeepney.bus_messages import message_bus  # noqa: E402
from jeepney.io.blocking import open_dbus_connection  # noqa: E402

PORTAL_BUS = 'org.freedesktop.portal.Desktop'
PORTAL_PATH = '/org/freedesktop/portal/desktop'
REQUEST_IFACE = 'org.freedesktop.portal.Request'
SESSION_IFACE = 'org.freedesktop.portal.Session'


class PortalError(RuntimeError):
    pass


class ScreenCastPortal:
    """Create one ScreenCast session and keep it alive until ``close``."""

    def __init__(self, timeout: float = 300.0):
        self.timeout = timeout
        self.conn = open_dbus_connection(bus='SESSION')
        self._match = MatchRule(type='signal', interface=REQUEST_IFACE,
                                member='Response')
        self.conn.send_and_get_reply(message_bus.AddMatch(self._match))
        self._response_filter = self.conn.filter(self._match, bufsize=64)
        self._responses = self._response_filter.queue
        self.session_handle: str | None = None
        self.node_id: int | None = None
        self.streams: list = []
        self._screencast = DBusAddress(PORTAL_PATH, bus_name=PORTAL_BUS,
                                       interface='org.freedesktop.portal.ScreenCast')

    @staticmethod
    def _restore_token_path() -> Path:
        base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(Path.home(), '.config')
        return Path(base) / 'g2-bridge' / 'portal-restore-token'

    def _load_restore_token(self) -> str | None:
        try:
            token = self._restore_token_path().read_text(encoding='utf-8').strip()
            return token or None
        except Exception:
            return None

    def _save_restore_token(self, token: str | None):
        if not token:
            return
        try:
            p = self._restore_token_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(token, encoding='utf-8')
        except Exception:
            pass

    def _request(self, method: str, signature: str, body: tuple):
        msg = new_method_call(self._screencast, method, signature, body)
        reply = self.conn.send_and_get_reply(msg, timeout=self.timeout)
        # Every ScreenCast request returns the request object path.
        return reply.body[0]

    def _response(self, request_path: str):
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PortalError('portal request timed out; select a screen in the dialog')
            try:
                msg = self.conn.recv_until_filtered(self._responses, timeout=remaining)
            except TimeoutError:
                raise PortalError('portal request timed out; select a screen in the dialog') from None
            path = msg.header.fields.get(HeaderFields.path)
            if path != request_path:
                continue
            code, results = msg.body
            if code != 0:
                raise PortalError(f'portal request failed with response code {code}')
            return results

    @staticmethod
    def _value(results, key, default=None):
        item = results.get(key) if results else None
        if item is None:
            return default
        # Jeepney unwraps a D-Bus variant into (signature, value). Arrays such
        # as ScreenCast ``streams`` are lists, not variant wrappers, so inspect
        # the shape before taking the value.
        if (isinstance(item, tuple) and len(item) == 2
                and isinstance(item[0], str) and item[0]
                and item[0][0] in 'abdhinoqstuxy({'):
            return item[1]
        return item

    def start(self, *, cursor: bool = True, source: int = 1) -> int:
        """Show the portal dialog and return the PipeWire node id.

        ``source`` is 1 for a monitor, 2 for a window, 3 for both.  Cursor
        embedding is requested so kmsgrab's missing pointer problem does not
        exist on this path.
        """
        token = 'g2_' + secrets.token_hex(8)
        request = self._request('CreateSession', 'a{sv}', ({
            'handle_token': ('s', token),
            'session_handle_token': ('s', token),
        },))
        results = self._response(request)
        self.session_handle = self._value(results, 'session_handle')
        if not self.session_handle:
            raise PortalError('portal did not return a session handle')

        token = 'g2_' + secrets.token_hex(8)
        options = {
            'types': ('u', source),
            'multiple': ('b', False),
            'cursor_mode': ('u', 2 if cursor else 1),
            'handle_token': ('s', token),
            # Ask portal to persist permission and return a restore token when supported.
            'persist_mode': ('u', 2),
        }
        restore_token = self._load_restore_token()
        if restore_token:
            options['restore_token'] = ('s', restore_token)
        request = self._request('SelectSources', 'oa{sv}', (
            self.session_handle,
            options,
        ))
        self._response(request)

        token = 'g2_' + secrets.token_hex(8)
        request = self._request('Start', 'osa{sv}', (
            self.session_handle,
            '',
            {'handle_token': ('s', token)},
        ))
        results = self._response(request)
        streams = self._value(results, 'streams', [])
        if not streams:
            raise PortalError('portal returned no screen streams')
        self.streams = streams
        first = streams[0]
        # Stream struct is (node_id: u, properties: a{sv}).
        if isinstance(first, (tuple, list)) and len(first) >= 2:
            node_value = first[0]
        else:
            node_value = first
        self.node_id = int(node_value)
        new_restore_token = self._value(results, 'restore_token')
        if isinstance(new_restore_token, str):
            self._save_restore_token(new_restore_token)
        return self.node_id

    def close(self):
        if self.session_handle:
            try:
                addr = DBusAddress(self.session_handle, bus_name=PORTAL_BUS,
                                   interface=SESSION_IFACE)
                self.conn.send_and_get_reply(new_method_call(addr, 'Close'))
            except Exception:
                pass
            self.session_handle = None
        try:
            self.conn.send_and_get_reply(message_bus.RemoveMatch(self._match))
        except Exception:
            pass
        try:
            self._response_filter.close()
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
