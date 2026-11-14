"""Experimental mobile (V2/AOA) session scaffolding.

NOTE: The exact mobile control handshake over AOA/LogicLink for Goggles 2/Integra
is not fully specified in this repo. On mobile, sim mode is reported as V1 0b/1a
in native flow but transport/wrapping details differ from PC USB.
This is a placeholder to allow engine integration and future implementation.
"""

import time


class MobileSessionError(RuntimeError):
    pass


class MobileSession:
    """Minimal placeholder session for mobile route experiments.

    Current behavior: reports ready immediately and provides no control traffic.
    Real AOA/V2 control handshake must be implemented for goggles to accept video.
    """

    def __init__(self):
        self.state = 'ready'
        self.identity = None
        self.model = 'Mobile (experimental)'

    def poll(self, now):
        return []

    def receive(self, reply, now):
        return []

    def reserve_sequence(self):
        # Not used for V2 video packetizer path in current engine integration.
        return 0
