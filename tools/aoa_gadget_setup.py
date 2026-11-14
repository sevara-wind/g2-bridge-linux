#!/usr/bin/env python3
"""Experimental: set up a Linux USB gadget (FunctionFS) to act as AOA accessory.

Requires:
  - UDC available (/sys/class/udc/<name>), role set to device
  - configfs mounted, usb_gadget available, usb_f_fs (FunctionFS) support
  - root privileges

NOTE: AOA strings/endpoints/protocol behavior for DJI goggles need validation.
This script sets up FunctionFS; a userspace process must handle EP0 AOA
control requests and bulk I/O via the mounted FunctionFS instance.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

GADGET_ROOT = Path("/sys/kernel/config/usb_gadget")


def sh(cmd, check=True):
    print("+", " ".join(cmd))
    r = subprocess.run(cmd, check=False)
    if check and r.returncode != 0:
        raise SystemExit(r.returncode)
    return r.returncode


def write(path: Path, text: str):
    path.write_text(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--udc", default=None, help="UDC name (default: first in /sys/class/udc)")
    ap.add_argument("--name", default="g2aoa", help="gadget configfs name")
    ap.add_argument("--ffs", default="ffs.aoa", help="FunctionFS instance name")
    ap.add_argument("--mnt", default="/run/g2-aoa/ffs", help="FunctionFS mountpoint")
    ap.add_argument("--cleanup", action="store_true")
    args = ap.parse_args()

    if os.geteuid() != 0:
        print("Run as root", file=sys.stderr)
        return 2

    udc = args.udc
    if not udc:
        udcs = sorted(os.listdir("/sys/class/udc")) if Path("/sys/class/udc").exists() else []
        if not udcs:
            print("No UDC found in /sys/class/udc", file=sys.stderr)
            return 1
        udc = udcs[0]

    gdir = GADGET_ROOT / args.name
    mnt = Path(args.mnt)

    if args.cleanup:
        try:
            write(gdir / "UDC", "\n")
        except Exception:
            pass
        subprocess.run(["umount", str(mnt)], check=False)
        for p in [
            gdir / "configs/c.1" / args.ffs,
            gdir / "configs/c.1/strings/0x409",
            gdir / "configs/c.1",
            gdir / "functions" / args.ffs,
            gdir / "strings/0x409",
            gdir,
        ]:
            try:
                if p.is_symlink() or p.is_file():
                    p.unlink()
                elif p.is_dir():
                    p.rmdir()
            except Exception:
                pass
        return 0

    if not GADGET_ROOT.exists():
        print(f"{GADGET_ROOT} not found (need configfs usb_gadget)", file=sys.stderr)
        return 1

    sh(["modprobe", "libcomposite"], check=False)
    rc = sh(["modprobe", "usb_f_fs"], check=False)
    if rc != 0:
        print("WARN: usb_f_fs module not available; FunctionFS gadget may fail.", file=sys.stderr)
        print("Check: find /lib/modules/$(uname -r) -name '*f_fs*' -o -name '*functionfs*'", file=sys.stderr)

    mnt.mkdir(parents=True, exist_ok=True)
    gdir.mkdir(parents=True, exist_ok=True)
    # Placeholder VID/PID (will change after AOA START re-enumeration on host side)
    write(gdir / "idVendor", "0x18d1")
    write(gdir / "idProduct", "0x2d00")
    (gdir / "strings/0x409").mkdir(parents=True, exist_ok=True)
    write(gdir / "strings/0x409/serialnumber", "g2bridge")
    write(gdir / "strings/0x409/manufacturer", "DJI")
    write(gdir / "strings/0x409/product", "com.dji.logiclink")
    (gdir / "configs/c.1/strings/0x409").mkdir(parents=True, exist_ok=True)
    write(gdir / "configs/c.1/MaxPower", "250")
    try:
        (gdir / "functions" / args.ffs).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Failed to create function {args.ffs}: {e}", file=sys.stderr)
        print("Available kernel function drivers/modules may be missing (e.g. usb_f_fs).", file=sys.stderr)
        return 1
    try:
        os.symlink(str(gdir / "functions" / args.ffs), str(gdir / "configs/c.1" / args.ffs))
    except FileExistsError:
        pass

    # Mount functionfs instance; userspace must open ep0 and implement AOA
    if not os.path.ismount(mnt):
        sh(["mount", "-t", "functionfs", args.ffs, str(mnt)], check=True)

    try:
        write(gdir / "UDC", udc + "\n")
    except Exception as e:
        print(f"Failed to bind UDC {udc}: {e}", file=sys.stderr)
        return 1
    print(f"Gadget bound to UDC {udc}. FunctionFS at {mnt}")
    print("Next: run userspace AOA/EP0 handler to respond to goggles (host) AOA requests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
