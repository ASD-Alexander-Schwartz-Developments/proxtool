# Copyright 2026 A.S.D - Alexander Schwartz Developments
# SPDX-License-Identifier: Apache-2.0
"""Make the wiki screenshots with made-up tags (no radio needed):
    python docs/wiki/make_screenshots.py      (Windows; the screen must be unlocked)
"""
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from PIL import ImageGrab  # noqa: E402  (only needed here)

from proxtool import gui, protocol as P, settings as S  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
NOW = time.time()
DEMO = [  # address, records, battery, clock offset s, flags
    ("C0:FF:EE:00:10:01", 37, 92, 0, P.FLAG_TIME_SET),
    ("C0:FF:EE:00:10:02", 0, 88, 1, P.FLAG_TIME_SET),
    ("C0:FF:EE:00:10:03", 12, 71, -5400, 0),          # restarted after a power cut
    ("C0:FF:EE:00:10:04", 214, 64, 0, P.FLAG_TIME_SET | P.FLAG_LOG_NEAR_FULL),
]


class FakeRadio:
    via = "ble"
    scan_error = None

    def snapshot(self):
        return {a: (P.Beacon("PRX", a, -1, bat, int(NOW + off), 1, fl, n), -60 - i * 4, time.time())
                for i, (a, n, bat, off, fl) in enumerate(DEMO)}

    def submit(self, coro):
        coro.close()

    def retry_scan(self):
        pass


def grab(win, name):
    win.update()
    x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(os.path.join(OUT, name))
    print("wrote", name)


def main():
    gui._dpi_aware()
    root = tk.Tk()
    gui.Radio = lambda *a, **k: FakeRadio()          # no Bluetooth for screenshots
    app = gui.App(root)
    app.outdir = r"D:\Study-2026\ProxTit"
    app.outvar.set(app.outdir)
    app.radio_choices = [("This computer's Bluetooth", "ble"), ("USB adapter (NCP) on COM7", "ncp:COM7")]
    app.radiobox.config(values=[c[0] for c in app.radio_choices])
    app.radiovar.set(app.radio_choices[0][0])
    app.logbox.configure(state="normal")
    app.logbox.delete("1.0", "end")
    app.logbox.configure(state="disabled")
    app.log("C0:FF:EE:00:10:01: 37 record(s) saved to D:\\Study-2026\\ProxTit\\C0FFEE001001.csv")
    app.log("C0:FF:EE:00:10:03: tag clock is off by -5400 s. Press 'Set clock' "
            "(records already stored keep their times).", error=True)
    root.attributes("-topmost", True)

    def step1():
        grab(root, "main-window.png")
        cur = {s.reg: int(round(s.default * s.scale)) for s in S.SETTINGS}
        d = gui.SettingsDialog(app, ["C0:FF:EE:00:10:01", "C0:FF:EE:00:10:02"], cur)
        d.win.attributes("-topmost", True)
        root.after(1500, lambda: (grab(d.win, "settings.png"), d.win.destroy(), root.destroy()))
    root.after(2500, step1)
    root.mainloop()


if __name__ == "__main__":
    main()
