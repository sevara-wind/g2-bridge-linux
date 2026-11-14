import unittest
from unittest.mock import patch

from scripts import stream_linux


def command(argv, encoder, *, filters=('h264_metadata', 'filter_units')):
    args = stream_linux.build_parser().parse_args(['--bitrate-mbps', '10', *argv])
    with patch.object(stream_linux, 'has_filter', side_effect=lambda _ffmpeg, name: name in filters):
        return stream_linux.build_command(args, encoder)


def bsf_value(cmd):
    return cmd[cmd.index('-bsf:v') + 1]


class BitstreamFilterTests(unittest.TestCase):
    """VAAPI CBR pads short frames with filler-data NALs. They are useless for
    the goggles and count against the frame-size limit, so strip them."""

    def test_vaapi_strips_filler_without_a_metadata_pass(self):
        self.assertEqual(bsf_value(command([], 'vaapi')),
                         'filter_units=remove_types=12')
        self.assertIn('-aud', command([], 'vaapi'))

    def test_libx264_uses_the_encoder_aud_flag(self):
        cmd = command(['--encoder', 'libx264'], 'libx264')
        self.assertEqual(cmd[cmd.index('-aud') + 1], '1')
        self.assertNotIn('-bsf:v', cmd)

    def test_vaapi_without_filter_units_is_rejected(self):
        with self.assertRaises(SystemExit):
            command([], 'vaapi', filters=('h264_metadata',))

    def test_no_aud_bsf_skips_the_vaapi_filter(self):
        cmd = command(['--no-aud-bsf'], 'vaapi')
        self.assertNotIn('-bsf:v', cmd)
        self.assertIn('-aud', cmd)


class SourceTests(unittest.TestCase):
    def test_v4l2_carries_the_input_options(self):
        cmd = command(['--source', 'v4l2', '--device', '/dev/video2', '--input-format', 'mjpeg',
                       '--input-size', '720x576', '--input-fps', '25'], 'libx264')
        self.assertEqual(cmd[cmd.index('-i') + 1], '/dev/video2')
        self.assertEqual(cmd[cmd.index('-input_format') + 1], 'mjpeg')
        self.assertEqual(cmd[cmd.index('-video_size') + 1], '720x576')
        self.assertEqual(cmd[cmd.index('-framerate') + 1], '25')

    def test_file_loops_in_real_time(self):
        cmd = command(['--source', 'file', '--file', 'clip.mp4'], 'libx264')
        self.assertIn('-stream_loop', cmd)
        self.assertEqual(cmd[cmd.index('-stream_loop') + 1], '-1')
        self.assertIn('-re', cmd)

    def test_kmsgrab_uses_the_drm_device_and_rotation(self):
        cmd = command(['--source', 'desktop', '--desktop-capture', 'kmsgrab',
                       '--kmsgrab-device', '/dev/dri/card1', '--kmsgrab-rotate', '270'], 'vaapi')
        self.assertEqual(cmd[cmd.index('-f') + 1], 'kmsgrab')
        self.assertEqual(cmd[cmd.index('-device') + 1], '/dev/dri/card1')
        self.assertIn('transpose=2', cmd[cmd.index('-vf') + 1])


if __name__ == '__main__':
    unittest.main()
