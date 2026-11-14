import unittest
from unittest.mock import patch

from goggles_bridge.portal import PortalError, ScreenCastPortal


class ScreenCastPortalTests(unittest.TestCase):
    def test_value_unwraps_dbus_variant_and_defaults(self):
        results = {'session_handle': ('s', '/org/freedesktop/portal/desktop/session/1')}
        self.assertEqual(ScreenCastPortal._value(results, 'session_handle'),
                         '/org/freedesktop/portal/desktop/session/1')
        self.assertEqual(ScreenCastPortal._value(results, 'missing', 'default'), 'default')

    def test_start_requests_monitor_and_embedded_cursor(self):
        response_values = iter([
            {'session_handle': ('s', '/org/freedesktop/portal/desktop/session/1')},
            {'session_handle': ('s', '/org/freedesktop/portal/desktop/session/1')},
            {'streams': [(1, 7)]},
        ])
        with patch.object(ScreenCastPortal, '_request') as request, \
                patch.object(ScreenCastPortal, '_response',
                             side_effect=lambda *args, **kwargs: next(response_values)) as response:
            portal = ScreenCastPortal(timeout=2)
            try:
                node_id = portal.start(cursor=True)
            finally:
                portal.close()

        self.assertEqual(node_id, 7)
        self.assertEqual(request.call_args_list[0].args[0:2], ('CreateSession', 'a{sv}'))
        self.assertEqual(request.call_args_list[1].args[0:2], ('SelectSources', 'oa{sv}'))
        self.assertEqual(request.call_args_list[2].args[0:2], ('Start', 'osa{sv}'))

        select_body = request.call_args_list[1].args[2][1]
        self.assertEqual(select_body['types'][1], 1)
        self.assertEqual(select_body['multiple'][1], False)
        self.assertEqual(select_body['cursor_mode'][1], 2)

    def test_start_can_hide_the_cursor(self):
        response_values = iter([
            {'session_handle': ('s', '/org/freedesktop/portal/desktop/session/1')},
            {'session_handle': ('s', '/org/freedesktop/portal/desktop/session/1')},
            {'streams': [(1, 7)]},
        ])
        with patch.object(ScreenCastPortal, '_request') as request, \
                patch.object(ScreenCastPortal, '_response',
                             side_effect=lambda *args, **kwargs: next(response_values)) as response:
            portal = ScreenCastPortal(timeout=2)
            try:
                portal.start(cursor=False)
            finally:
                portal.close()

        select_body = request.call_args_list[1].args[2][1]
        self.assertEqual(select_body['cursor_mode'][1], 1)

    def test_start_reports_missing_streams(self):
        response_values = iter([
            {'session_handle': ('s', '/org/freedesktop/portal/desktop/session/1')},
            {'session_handle': ('s', '/org/freedesktop/portal/desktop/session/1')},
            {'streams': []},
        ])
        with patch.object(ScreenCastPortal, '_request') as request, \
                patch.object(ScreenCastPortal, '_response',
                             side_effect=lambda *args, **kwargs: next(response_values)) as response:
            portal = ScreenCastPortal(timeout=2)
            try:
                with self.assertRaises(PortalError):
                    portal.start()
            finally:
                portal.close()


if __name__ == '__main__':
    unittest.main()
