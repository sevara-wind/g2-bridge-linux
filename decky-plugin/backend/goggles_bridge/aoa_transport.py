"""Experimental AOA (Android Open Accessory) transport for mobile/V2 route.

Goal: allow the host machine to act as a USB accessory (device/gadget role)
so that DJI goggles, acting as USB host, can connect via AOA and exchange
V2/LogicLink packets without the PC-route ~56 KB frame limit.

Status: scaffold only. AOA negotiation, gadget/FunctionFS setup, endpoint I/O,
and V2 control session integration are TODO.

Typical Linux prerequisites (hardware-dependent, e.g. DRD USB-C):
- USB gadget/ConfigFS support (configfs mounted, udc available)
- Ability to switch port to device role (Type-C role switch / DRD)
- Permission to configure gadgets (usually root)

High-level steps to investigate:
1. Check role/gadget capability:
   - /sys/class/typec/port*/{data_role,power_role,port_type}
   - /sys/class/udc/* and /sys/kernel/config/usb_gadget
2. Implement AOA 1.0/2.0 negotiation (GET_PROTOCOL, SEND_STRINGs, START)
   with accessory strings expected by goggles (see mobile app identifiers,
   e.g. DJI/com.dji.logiclink/com.dji.link - needs validation).
3. After START, goggles re-enumerate; open bulk IN/OUT endpoints and
   speak V2 + LogicLink (goggles_bridge.protocol).
4. Implement V2 control/session flow over the AOA bulk channel.

References in repo:
- docs/PROTOCOL.md
- docs/research/MOBILE_PROTOCOL.md
"""

class AoaTransportError(RuntimeError):
    """AOA transport is unavailable or failed."""


class AoaTransport:
    def __init__(self):
        raise AoaTransportError('AOA transport not implemented yet (DRD/gadget + AOA negotiation required)')

    def read(self, timeout_ms=100):
        return b''

    def write(self, data):
        raise AoaTransportError('AOA transport not implemented yet')

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
