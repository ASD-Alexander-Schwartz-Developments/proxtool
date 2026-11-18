# Third-party software in proxtool

proxtool (© 2026 A.S.D - Alexander Schwartz Developments, Apache License 2.0)
uses the open-source components below. All are under permissive licences: they may be used and
redistributed in open or closed software, provided their copyright and licence
notices are kept, as this file does.

| Component | Used for | Licence | Copyright | Where |
|---|---|---|---|---|
| Python | runtime | PSF License 2.0 | Python Software Foundation | <https://docs.python.org/3/license.html> |
| Tkinter / Tcl/Tk | the window | PSF (Tkinter); Tcl/Tk licence (BSD-style) | PSF; Regents of the University of California, Sun Microsystems and others | <https://www.tcl.tk/software/tcltk/license.html> |
| bleak | Bluetooth LE (all platforms) | MIT | Henrik Blidh and contributors | <https://github.com/hbldh/bleak> |
| pywinrt (`winrt-*` packages) | Bluetooth on Windows | MIT | the pywinrt contributors | <https://github.com/pywinrt/pywinrt> |
| dbus-fast | Bluetooth on Linux (BlueZ over D-Bus) | MIT | Bluetooth Devices authors and contributors | <https://github.com/Bluetooth-Devices/dbus-fast> |
| typing_extensions | Python compatibility | PSF License 2.0 | Python Software Foundation | <https://github.com/python/typing_extensions> |
| async-timeout (Python < 3.11 only) | timeouts | Apache License 2.0 | aio-libs contributors | <https://github.com/aio-libs/async-timeout> |
| pyBGAPI (optional, `ncp` transport) | talking to a Silicon Labs NCP adapter | zlib | Silicon Laboratories Inc. | <https://pypi.org/project/pybgapi/> |
| pySerial (optional, `ncp` transport) | the adapter's serial port | BSD-3-Clause | Chris Liechti | <https://github.com/pyserial/pyserial> |
| `proxtool/api/sl_bt-9.0.0.xapi`, `sl_bt-11.0.1.xapi` (shipped) | Bluetooth API definitions for pyBGAPI (Simplicity SDK 2024.12 and 2025.12), from Silicon Labs' pybgapi-examples | zlib | Silicon Laboratories Inc. | see the zlib text below |

Not shipped: Pillow (MIT-CMU) was used once to make the icon files in `assets/`.
macOS (pyobjc, MIT) is not supported.

The firmware update speaks the Silicon Labs AppLoader OTA DFU protocol (public
Silicon Labs documentation, AN1086). Apart from the shipped `.xapi`
definition files and the altered pyBGAPI routine above, no Silicon Labs code is
part of proxtool.
The ASD name and logo (`assets/`) are trademarks of A.S.D and are not covered
by any open-source licence.

When proxtool is packaged as a stand-alone program (e.g. a Windows .exe made
with PyInstaller), the packaged Python and libraries are redistributed: ship
this file with it. PyInstaller itself is GPL-2.0 with an exception that
explicitly allows packaged programs under any licence.

## zlib licence text (pyBGAPI, sl_bt.xapi)

Copyright 2021 Silicon Laboratories Inc. www.silabs.com

This software is provided 'as-is', without any express or implied warranty. In
no event will the authors be held liable for any damages arising from the use
of this software.

Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it
freely, subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not claim
   that you wrote the original software. If you use this software in a
   product, an acknowledgment in the product documentation would be
   appreciated but is not required.
2. Altered source versions must be plainly marked as such, and must not be
   misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.

The `.xapi` files are shipped unaltered. `proxtool/ncp.py` contains an **altered**
copy of pyBGAPI's `BGApiConnHandler.run` (pyBGAPI 1.3): it skips messages the
definition does not know instead of stopping; it is marked as altered there.

## MIT licence text (bleak, pywinrt, dbus-fast)

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

The PSF License 2.0 and the Apache License 2.0 texts are at
<https://docs.python.org/3/license.html> and
<https://www.apache.org/licenses/LICENSE-2.0>.
