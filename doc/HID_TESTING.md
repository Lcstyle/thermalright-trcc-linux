# HID Device Testing Guide

The HID protocol is implemented with **563 automated tests** but **not tested against real hardware**. I only have a SCSI device (`87CD:70DB`). If you have an HID device, please help test.

## Supported HID Devices

Run `lsusb` and look for your VID:PID:

| VID:PID | lsusb shows | Protocol |
|---------|-------------|----------|
| `0416:5302` | Winbond Electronics Corp. USBDISPLAY | HID Type 2 (LCD) |
| `0418:5303` | ALi Corp. LCD Display | HID Type 3 (LCD) |
| `0418:5304` | ALi Corp. LCD Display | HID Type 3 (LCD) |
| `0416:8001` | Winbond Electronics Corp. LED Controller | HID LED (RGB) |

## How to test

Install TRCC normally (see [README](../README.md#install)), then run with the `--testing-hid` flag:

```bash
trcc --testing-hid detect       # Check if your device is found
trcc --testing-hid gui          # Launch the GUI with HID support
```

That's it — no branch switching needed. The `--testing-hid` flag enables HID device detection.

## What to report

Open an [issue](https://github.com/Lexonight1/thermalright-trcc-linux/issues) with:

1. Your `lsusb` line (VID:PID and device name)
2. Output of `trcc --testing-hid detect`
3. Does the GUI launch and detect the device?
4. Can you send an image to the LCD? Does it display correctly?
5. Your distro and kernel version (`uname -r`)

Even a "it doesn't work" report is helpful — it tells me where the protocol breaks.

## How it works

HID devices use a different protocol than SCSI devices:

- **SCSI** (`87CD:70DB`, `0416:5406`, `0402:3922`) — USB Mass Storage, sends raw RGB565 pixels via `sg_raw`
- **HID Type 2** (`0416:5302`) — USB HID, DA/DB/DC/DD handshake, 512-byte aligned JPEG frames
- **HID Type 3** (`0418:5303`, `0418:5304`) — USB HID, F5 prefix, fixed-size frames with ACK
- **HID LED** (`0416:8001`) — USB HID, 64-byte reports for RGB LED color control

Resolution is auto-detected via the DA/DB/DC/DD handshake — the device reports its screen type, which maps to a resolution (240x240, 320x320, 480x480, etc.).
