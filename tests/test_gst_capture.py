import unittest
from unittest.mock import patch

from goggles_bridge import gst_capture


class GstCaptureTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(gst_capture, 'pick_portal_encoder', return_value='x264')
        self.mock_encoder = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(gst_capture, 'gst_launch', return_value='/usr/bin/gst-launch-1.0')
        self.mock_launch = patcher.start()
        self.addCleanup(patcher.stop)

    def test_portal_x264_pipeline_targets_goggles_frame_limit(self):
        pipeline = gst_capture.build_pipeline(42, fps=60, bitrate_mbps=10)
        self.assertIn('pipewiresrc path=42 always-copy=true', pipeline)
        self.assertIn('x264enc speed-preset=ultrafast tune=zerolatency pass=cbr '
                      'bitrate=10000 key-int-max=180 aud=true bframes=0 rc-lookahead=0 '
                      'sync-lookahead=0 sliced-threads=true', pipeline)
        # 10 Mbps CBR at 60 fps must keep a keyframe below the 56 KB goggles limit.
        self.assertIn('vbv-buf-capacity=125', pipeline)
        self.assertIn('h264parse config-interval=-1', pipeline)
        self.assertIn('avimux', pipeline)
        self.assertIn('fdsink fd=1 sync=false', pipeline)

    def test_portal_x264_vbv_budget_follows_bitrate(self):
        self.assertIn('vbv-buf-capacity=125', gst_capture.build_pipeline(42, fps=60, bitrate_mbps=10))
        self.assertIn('vbv-buf-capacity=104', gst_capture.build_pipeline(42, fps=60, bitrate_mbps=12))
        self.assertIn('vbv-buf-capacity=89', gst_capture.build_pipeline(42, fps=60, bitrate_mbps=14))

    def test_portal_command_is_split_into_argv_tokens(self):
        command = gst_capture.build_command(42, fps=60, bitrate_mbps=10)
        self.assertEqual(command[:3], ['/usr/bin/gst-launch-1.0', '-q', '-e'])
        pipeline = command[3:]
        self.assertIn('!', pipeline)
        self.assertTrue(any(token.startswith('pipewiresrc') for token in pipeline))

    def test_portal_check_uses_num_buffers_and_split_tokens(self):
        command = gst_capture.build_command(42, fps=60, bitrate_mbps=10, frames=2)
        pipeline = command[3:]
        self.assertIn('pipewiresrc', pipeline)
        self.assertIn('path=42', pipeline)
        self.assertIn('always-copy=true', pipeline)
        self.assertIn('num-buffers=2', pipeline)
        self.assertIn('fdsink', pipeline)

    def test_portal_rotation_uses_a_video_flip(self):
        pipeline = gst_capture.build_pipeline(42, fps=60, bitrate_mbps=10, rotate='90')
        self.assertIn('videoflip method=clockwise', pipeline)
        pipeline = gst_capture.build_pipeline(42, fps=60, bitrate_mbps=10, rotate='270')
        self.assertIn('videoflip method=counterclockwise', pipeline)
        self.assertNotIn('videoflip', gst_capture.build_pipeline(42, fps=60, bitrate_mbps=10))

    def test_portal_vaapi_uses_gstreamer_vaapi_encoder(self):
        self.mock_encoder.return_value = 'vaapi'
        pipeline = gst_capture.build_pipeline(42, fps=60, bitrate_mbps=10, encoder='vaapi')
        self.assertIn('vaapih264enc rate-control=cbr bitrate=10000 keyframe-period=180 '
                      'max-bframes=0 aud=true', pipeline)
        self.assertNotIn('x264enc', pipeline)


if __name__ == '__main__':
    unittest.main()
