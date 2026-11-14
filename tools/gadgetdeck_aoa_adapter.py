#!/usr/bin/env python3
"""Adapt GadgetDeck-style configfs gadget management for AOA/FFS experiments.

Based on GadgetDeck's gadget-deck-manager.py approach (DRD + configfs + UDC),
but targets FunctionFS (ffs.aoa) for Android Open Accessory / mobile bridge
use-cases (e.g. DJI goggles mobile route relay). On kernels without usb_f_fs
this will fail at function creation - see diagnostics.
"""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

GADGET_ROOT = Path('/sys/kernel/config/usb_gadget')
DEFAULT_NAME = 'g2-aoa'


def write(path: Path, data: str | bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 'wb' if isinstance(data, (bytes, bytearray)) else 'w'
    with open(path, mode) as f:
        f.write(data)


def read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except Exception:
        return ''


def udcs():
    return sorted(p.name for p in Path('/sys/class/udc').iterdir()) if Path('/sys/class/udc').exists() else []


def gadget_path(name: str) -> Path:
    return GADGET_ROOT / name


def ensure_configfs():
    if not GADGET_ROOT.exists():
        raise SystemExit(f'configfs usb_gadget not available: {GADGET_ROOT}')


def setup(name: str, vid='0x18d1', pid='0x2d00', manufacturer='OpenCode', product='G2 AOA Bridge', serial='0123456789'):
    ensure_configfs()
    g = gadget_path(name)
    if g.exists():
        raise SystemExit(f'Gadget already exists: {g} (run destroy first)')
    g.mkdir(parents=True)
    write(g/'idVendor', vid)
    write(g/'idProduct', pid)
    write(g/'bcdUSB', '0x0200')
    strings = g/'strings'/'0x409'
    strings.mkdir(parents=True, exist_ok=True)
    write(strings/'serialnumber', serial)
    write(strings/'manufacturer', manufacturer)
    write(strings/'product', product)

    cfg = g/'configs'/'c.1'
    (cfg/'strings'/'0x409').mkdir(parents=True, exist_ok=True)
    write(cfg/'bmAttributes', '0xc0')
    write(cfg/'MaxPower', '500')
    write(cfg/'strings'/'0x409'/'configuration', 'AOA')

    # FunctionFS instance (requires usb_f_fs in kernel)
    func = g/'functions'/'ffs.aoa'
    try:
        func.mkdir()
    except OSError as e:
        raise SystemExit(
            f'Failed to create ffs.aoa (missing usb_f_fs/kernel support?): {e}\n'
            f'UDCs: {udcs()}\nCheck: /lib/modules/$(uname -r)/kernel/drivers/usb/gadget/function'
        )
    os.symlink(str(func), str(cfg/'ffs.aoa'))
    print(f'Created gadget {g}. Mount functionfs and run userspace daemon, then activate with UDC.')
    print('Example: mkdir -p /dev/ffs-aoa && mount -t functionfs aoa /dev/ffs-aoa')


def activate(name: str, udc: str | None = None):
    g = gadget_path(name)
    if not g.exists():
        raise SystemExit(f'Gadget not found: {g}')
    if not udc:
        avail = udcs()
        if not avail:
            raise SystemExit('No UDC available in /sys/class/udc')
        udc = avail[0]
    write(g/'UDC', udc)
    print(f'Activated {name} on UDC {udc}')


def deactivate(name: str):
    g = gadget_path(name)
    if not g.exists():
        return
    try:
        write(g/'UDC', '\n')
    except Exception:
        try:
            write(g/'UDC', '')
        except Exception:
            pass
    print(f'Deactivated {name}')


def destroy(name: str):
    g = gadget_path(name)
    if not g.exists():
        print(f'No gadget {g}')
        return
    deactivate(name)
    # remove config links
    cfg = g/'configs'/'c.1'
    if cfg.exists():
        for p in list(cfg.iterdir()):
            if p.is_symlink():
                p.unlink()
        strings = cfg/'strings'/'0x409'
        if strings.exists():
            strings.rmdir()
        if (cfg/'strings').exists():
            try: (cfg/'strings').rmdir()
            except Exception: pass
        try: cfg.rmdir()
        except Exception: pass
    funcs = g/'functions'
    if funcs.exists():
        for p in list(funcs.iterdir()):
            try: p.rmdir()
            except Exception: pass
    strs = g/'strings'/'0x409'
    if strs.exists():
        try: strs.rmdir()
        except Exception: pass
    if (g/'strings').exists():
        try: (g/'strings').rmdir()
        except Exception: pass
    try: g.rmdir()
    except Exception as e:
        raise SystemExit(f'Failed to remove gadget dir: {e}')
    print(f'Destroyed {name}')


def status(name: str):
    g = gadget_path(name)
    print('gadget:', g, 'exists=' + str(g.exists()))
    print('udcs:', udcs())
    role = Path('/sys/class/usb_role/dwc3.1.auto-role-switch/role')
    if role.exists():
        print('role:', read(role))
    if g.exists():
        print('UDC:', read(g/'UDC') or '(none)')
        print('functions:', [p.name for p in (g/'functions').iterdir()] if (g/'functions').exists() else [])
    func_dir = Path('/lib/modules')/os.uname().release/'kernel/drivers/usb/gadget/function'
    print('kernel_gadget_functions:', [p.name for p in func_dir.iterdir()] if func_dir.exists() else '(missing)')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', default=DEFAULT_NAME)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status')
    s = sub.add_parser('setup')
    s.add_argument('--vid', default='0x18d1')
    s.add_argument('--pid', default='0x2d00')
    sub.add_parser('activate').add_argument('--udc')
    sub.add_parser('deactivate')
    sub.add_parser('destroy')
    args = ap.parse_args()
    if args.cmd == 'status':
        status(args.name)
    elif args.cmd == 'setup':
        setup(args.name, vid=args.vid, pid=args.pid)
    elif args.cmd == 'activate':
        activate(args.name, args.udc)
    elif args.cmd == 'deactivate':
        deactivate(args.name)
    elif args.cmd == 'destroy':
        destroy(args.name)


if __name__ == '__main__':
    main()
