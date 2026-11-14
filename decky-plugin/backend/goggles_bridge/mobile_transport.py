"""Experimental mobile/AOA transport abstractions.

The PC route uses ControlUsb (MI04 bulk, V1). The mobile/AOA route needs a
different byte transport (e.g. AOA bulk endpoints via gadget/relay).

This module provides:
- MobileTransportError
- TcpRelayTransport: simple length-prefixed or raw stream transport over TCP,
  useful for relaying H.264/V2 traffic to an external AOA-capable device.
"""

import socket


class MobileTransportError(RuntimeError):
    pass


class TcpRelayTransport:
    """Raw bidirectional TCP byte transport for external AOA relay experiments.

    Protocol on the wire is application-defined; by default this just sends and
    receives raw bytes. A relay device/service can bridge this to AOA bulk I/O.
    """

    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self.sock = None
        self.closed = False

    def connect(self):
        if self.sock is not None:
            return
        try:
            s = socket.create_connection((self.host, self.port), timeout=self.timeout)
            s.settimeout(0.05)
            self.sock = s
        except OSError as e:
            raise MobileTransportError(f'TCP relay connect failed: {e}') from e

    def read(self, timeout_ms=100):
        if self.closed:
            raise MobileTransportError('Transport is closed')
        if self.sock is None:
            self.connect()
        self.sock.settimeout(max(0.001, timeout_ms / 1000.0))
        try:
            data = self.sock.recv(4096)
            if data == b'':
                raise MobileTransportError('TCP relay connection closed')
            return data
        except socket.timeout:
            return b''
        except OSError as e:
            raise MobileTransportError(str(e)) from e

    def write(self, data):
        if self.closed:
            raise MobileTransportError('Transport is closed')
        if self.sock is None:
            self.connect()
        data = bytes(data)
        try:
            self.sock.sendall(data)
        except OSError as e:
            raise MobileTransportError(str(e)) from e

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.sock is not None:
                self.sock.close()
        finally:
            self.sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()
