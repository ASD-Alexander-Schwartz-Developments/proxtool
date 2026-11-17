# Copyright 2026 A.S.D - Alexander Schwartz Developments
# SPDX-License-Identifier: Apache-2.0
"""proxtool window: find ProxTit BLE tags, download their logs, set their clocks
and settings. Windows and Linux (Python with Tkinter, bleak; on Linux BlueZ).

    proxtool-gui          (or: python -m proxtool.gui, or: proxtool gui)

All Bluetooth work runs in one background thread with its own asyncio loop, one
operation at a time; the window only shows results. Downloads use the same
files and the same safe procedure as `proxtool download`: each batch is written
to disk before the tag is told it may delete it.
"""
from __future__ import annotations

import asyncio
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable, Dict, List, Optional

from . import model as M
from . import protocol as P
from . import settings as S
from .cli import append_csv, csv_path, iso

TITLE = "ProxTit Tags"


# ---- Bluetooth thread -------------------------------------------------------------

class Radio:
    """Scanning plus one tag operation at a time, in a background thread, through
    a transport (link.py): this computer's Bluetooth or a USB NCP adapter."""

    def __init__(self, post: Callable[[Callable[[], None]], None], via: str = "ble"):
        self.post = post                    # run a function on the window's thread
        self.loop = asyncio.new_event_loop()
        self.seen: Dict[str, tuple] = {}
        self.lock = threading.Lock()
        self.scanning = False
        self.scan_error: Optional[str] = None
        self.transport = None
        self.via = via
        threading.Thread(target=self._run, daemon=True, name="proxtool-radio").start()
        self.submit(self._switch(via))

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def snapshot(self) -> Dict[str, tuple]:
        with self.lock:
            return dict(self.seen)

    async def _switch(self, via: str) -> None:
        from . import link as L
        await self._stop_scan()
        if self.transport is not None:
            try:
                await self.transport.close()
            except Exception:
                pass
        self.transport = None
        with self.lock:
            self.seen.clear()
        self.via = via
        try:
            self.transport = L.make(via)
            L.use(self.transport)
        except (SystemExit, Exception) as e:
            self.scan_error = str(e) or type(e).__name__
            return
        await self._start_scan()

    def switch(self, via: str) -> None:
        self.submit(self._switch(via))

    async def _start_scan(self) -> None:
        if self.scanning or self.transport is None:
            return

        def cb(b, rssi, wall):
            with self.lock:
                self.seen[b.uid] = (b, rssi, wall)
        try:
            await self.transport.start_scan(cb)
            self.scanning = True
            self.scan_error = None
        except (SystemExit, Exception) as e:     # Bluetooth off, no adapter, ...
            self.scanning = False
            self.scan_error = _err(e) if isinstance(e, Exception) else str(e)

    async def _stop_scan(self) -> None:
        if self.scanning and self.transport is not None:
            try:
                await self.transport.stop_scan()
            finally:
                self.scanning = False

    def run_on_tag(self, address: str, fn, done: Callable[[object, Optional[str]], None]) -> None:
        """Connect, run `await fn(tag)`, disconnect; then done(result, error) on the
        window thread. Scanning pauses meanwhile (connections are more reliable)."""
        from .tag import Tag

        async def job():
            await self._stop_scan()
            try:
                if self.transport is None:
                    raise RuntimeError(self.scan_error or "no radio")
                async with Tag(address, self.transport) as t:
                    return await fn(t), None
            except Exception as e:
                return None, _err(e)
            finally:
                await self._start_scan()

        fut = self.submit(job())
        fut.add_done_callback(lambda f: self.post(lambda: done(*f.result())))

    def run_job(self, make_coro, done: Callable[[object, Optional[str]], None]) -> None:
        """Like run_on_tag for work that makes its own connections (firmware update)."""
        async def job():
            await self._stop_scan()
            try:
                return await make_coro(), None
            except Exception as e:
                return None, _err(e)
            finally:
                await self._start_scan()

        fut = self.submit(job())
        fut.add_done_callback(lambda f: self.post(lambda: done(*f.result())))

    def retry_scan(self) -> None:
        self.submit(self._start_scan())


def _err(e: Exception) -> str:
    msg = str(e) or type(e).__name__
    if type(e).__name__ in ("TimeoutError", "BleakDeviceNotFoundError"):
        msg += " (is the tag in range and awake? A tag in Off mode needs the magnet)"
    return msg


# ---- branding ---------------------------------------------------------------------------

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _image(name: str):
    try:
        return tk.PhotoImage(file=os.path.join(ASSETS, name))
    except tk.TclError:
        return None


def _set_icon(win) -> None:
    """ASD icon on the window and the taskbar (.ico on Windows, .png elsewhere)."""
    try:
        if sys.platform.startswith("win"):
            win.iconbitmap(default=os.path.join(ASSETS, "asd-icon.ico"))
        else:
            img = _image("asd-icon.png")
            if img is not None:
                win.iconphoto(True, img)
                win._asd_icon = img             # keep a reference
    except tk.TclError:
        pass


# ---- window -------------------------------------------------------------------------

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.prefs = M.load_prefs()
        self.outdir = self.prefs.get("outdir") or M.default_outdir()
        self.inbox: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self.busy = False
        self.jobs: List[Callable[[], None]] = []

        root.title(TITLE)
        _set_icon(root)
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)    # display scaling (DPI aware)
        root.geometry(f"{self.px(900)}x{self.px(560)}")
        root.minsize(self.px(720), self.px(420))
        ttk.Style(root).configure("Treeview", rowheight=self.px(22))
        self._build()
        self.visited: Dict[str, float] = {}     # auto-download: tag -> last visit
        self.radio = Radio(self.inbox.put, self.prefs.get("via", "ble"))
        self._fill_radios()
        self._after = {}
        self._after["pump"] = root.after(100, self._pump)
        self._after["refresh"] = root.after(1000, self._refresh)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.log(f"Looking for tags. Downloads are saved in {self.outdir}")

    def px(self, n: float) -> int:
        """Pixels at 100 % display scaling -> pixels on this display."""
        return int(round(n * self.scale))

    # -- layout --
    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Save downloads in:").pack(side="left")
        self.outvar = tk.StringVar(value=self.outdir)
        ttk.Entry(top, textvariable=self.outvar, state="readonly").pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(top, text="Change...", command=self._choose_outdir).pack(side="left")
        ttk.Button(top, text="Open folder", command=self._open_outdir).pack(side="left", padx=(6, 0))
        self._logo = _image("asd-logo.png")
        if self._logo is not None:
            ttk.Label(top, image=self._logo, cursor="hand2").pack(side="right", padx=(12, 0))
        ttk.Button(top, text="About", command=self._about).pack(side="right", padx=(12, 0))

        bar = ttk.Frame(self.root)
        bar.pack(fill="x", **pad)
        ttk.Label(bar, text="Reach tags with:").pack(side="left")
        self.radiovar = tk.StringVar()
        self.radiobox = ttk.Combobox(bar, textvariable=self.radiovar, state="readonly", width=46)
        self.radiobox.pack(side="left", padx=6)
        self.radiobox.bind("<<ComboboxSelected>>", self._radio_chosen)
        ttk.Button(bar, text="Refresh list", command=self._fill_radios).pack(side="left")
        self.autovar = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Download and set the clock of tags in range automatically",
                        variable=self.autovar, command=self._auto_toggled).pack(side="right")

        mid = ttk.Frame(self.root)
        mid.pack(fill="both", expand=True, **pad)
        self.tree = ttk.Treeview(mid, columns=[c[0] for c in M.COLUMNS], show="headings", selectmode="extended")
        for key, head, width in M.COLUMNS:
            self.tree.heading(key, text=head)
            self.tree.column(key, width=self.px(width), anchor="w")
        self.tree.tag_configure("warn", foreground="#b00020")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")

        btns = ttk.Frame(self.root)
        btns.pack(fill="x", **pad)
        self.buttons = [
            ttk.Button(btns, text="Download", command=self._download_selected),
            ttk.Button(btns, text="Download all", command=self._download_all),
            ttk.Button(btns, text="Set clock", command=self._set_clock),
            ttk.Button(btns, text="Settings...", command=self._settings),
            ttk.Button(btns, text="Details...", command=self._details),
            ttk.Button(btns, text="Update firmware...", command=self._update_firmware),
        ]
        for b in self.buttons:
            b.pack(side="left", padx=(0, 6))
        ttk.Label(btns, text="Select one or more tags (Ctrl/Shift-click).", foreground="#555").pack(side="right")

        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", **pad)
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(fill="x")
        self.status = ttk.Label(bottom, text="")
        self.status.pack(fill="x")
        self.logbox = ScrolledText(self.root, height=8, state="disabled", wrap="word", font="TkDefaultFont")
        self.logbox.pack(fill="both", padx=8, pady=(0, 8))
        self.logbox.tag_configure("err", foreground="#b00020")

    # -- plumbing --
    def _pump(self) -> None:
        while True:
            try:
                fn = self.inbox.get_nowait()
            except queue.Empty:
                break
            fn()
        self._after["pump"] = self.root.after(100, self._pump)

    def _refresh(self) -> None:
        rows = M.tag_rows(self.radio.snapshot(), time.time())
        sel = set(self.tree.selection())
        have = set(self.tree.get_children())
        for r in rows:
            tags = () if r.clock_ok else ("warn",)
            if r.uid in have:
                self.tree.item(r.uid, values=r.values(), tags=tags)
            else:
                self.tree.insert("", "end", iid=r.uid, values=r.values(), tags=tags)
        for gone in have - {r.uid for r in rows}:
            if gone not in sel:
                self.tree.delete(gone)
        if self.radio.scan_error and not self.busy:
            self.status.config(text=f"Bluetooth: {self.radio.scan_error}. Retrying...")
            self.radio.retry_scan()
        elif not self.busy:
            self.status.config(text=f"{len(rows)} tag(s) in range")
        if self.autovar.get() and not self.busy:
            now = time.time()
            due = [r for r in rows if M.due(r, now, self.visited.get(r.uid, 0))]
            if due:
                steps = []
                for r in due:
                    self.visited[r.uid] = now
                    if not r.clock_ok:
                        steps.append(self._clock_step(r.uid))
                    if r.records > 0:
                        steps.append(self._download_step(r.uid, r.records))
                self._queue(steps)
        self._after["refresh"] = self.root.after(1000, self._refresh)

    # -- radio choice and automatic mode --
    def _fill_radios(self) -> None:
        from . import ncp
        self.radio_choices = [("This computer's Bluetooth", "ble")]
        for port, desc in ncp.candidate_ports():
            self.radio_choices.append((f"USB adapter (NCP) on {port}: {desc}", f"ncp:{port}"))
        self.radiobox.config(values=[c[0] for c in self.radio_choices])
        cur = self.radio.via
        names = [c[0] for c in self.radio_choices if c[1] == cur]
        self.radiovar.set(names[0] if names else self.radio_choices[0][0])

    def _radio_chosen(self, _evt=None) -> None:
        via = dict(self.radio_choices).get(self.radiovar.get(), "ble")
        if via == self.radio.via:
            return
        self.radio.switch(via)
        self.prefs["via"] = via
        M.save_prefs(self.prefs)
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.log(f"Now using: {self.radiovar.get()}")

    def _auto_toggled(self) -> None:
        if self.autovar.get():
            self.visited.clear()
            self.log("Automatic mode: every tag in range with records waiting, or a wrong clock, is "
                     f"downloaded and its clock set, at most once every {M.REVISIT_S} s. Keep this window open.")
        else:
            self.log("Automatic mode off.")

    def close(self) -> None:
        for a in self._after.values():
            try:
                self.root.after_cancel(a)
            except tk.TclError:
                pass
        try:
            self.radio.submit(self.radio._stop_scan()).result(timeout=3)
        except Exception:
            pass
        self.root.destroy()

    def log(self, text: str, error: bool = False) -> None:
        self.logbox.configure(state="normal")
        self.logbox.insert("end", time.strftime("%H:%M:%S ") + text + "\n", ("err",) if error else ())
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _selected(self) -> List[str]:
        sel = list(self.tree.selection())
        if not sel:
            messagebox.showinfo(TITLE, "Select a tag in the list first.")
        return sel

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.busy = busy
        for b in self.buttons:
            b.state(["disabled"] if busy else ["!disabled"])
        if text:
            self.status.config(text=text)
        if not busy:
            self.progress.config(value=0)

    def _queue(self, steps: List[Callable[[Callable[[], None]], None]]) -> None:
        """Run steps one after the other; each calls its argument when finished."""
        self._set_busy(True)

        def next_step(i=0):
            if i >= len(steps):
                self._set_busy(False)
                return
            steps[i](lambda: next_step(i + 1))
        next_step()

    # -- folder --
    def _choose_outdir(self) -> None:
        d = filedialog.askdirectory(initialdir=self.outdir, title="Save downloads in")
        if d:
            self.outdir = d
            self.outvar.set(d)
            self.prefs["outdir"] = d
            M.save_prefs(self.prefs)

    def _open_outdir(self) -> None:
        os.makedirs(self.outdir, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(self.outdir)          # noqa: (Windows only)
        else:
            import subprocess
            subprocess.Popen(["xdg-open", self.outdir])

    # -- download --
    def _download_selected(self) -> None:
        sel = self._selected()
        if sel:
            self._queue([self._download_step(a) for a in sel])

    def _download_all(self) -> None:
        rows = [r for r in M.tag_rows(self.radio.snapshot(), time.time()) if r.records > 0]
        if not rows:
            messagebox.showinfo(TITLE, "No tag in range has records waiting.")
            return
        self._queue([self._download_step(r.uid) for r in rows])

    def _clock_step(self, address: str):
        def step(finished):
            self.status.config(text=f"Setting the clock of {address}...")

            def done(res, err):
                if err:
                    self.log(f"{address}: set clock failed: {err}", error=True)
                else:
                    self.log(f"{address}: clock set to {iso(res)} UTC")
                finished()
            self.radio.run_on_tag(address, lambda t: t.set_time(), done)
        return step

    def _download_step(self, address: str, expected: int = 0):
        def step(finished):
            os.makedirs(self.outdir, exist_ok=True)
            path = csv_path(self.outdir, address)
            self.status.config(text=f"Downloading {address}...")
            self.progress.config(value=0)

            def prog(n, total):
                self.inbox.put(lambda: self.progress.config(value=100.0 * n / max(total, n, 1)))

            async def fn(t):
                n = await t.download(lambda recs: append_csv(path, recs), progress=prog, expected=expected)
                return n, await t.page()

            def done(res, err):
                if err:
                    self.log(f"{address}: download failed: {err}. Records not yet confirmed stay on the tag; "
                             "try again.", error=True)
                else:
                    n, page = res
                    self.log(f"{address}: {n} record(s) saved to {path}")
                    if page.pending:
                        self.log(f"{address}: {page.pending} record(s) still on the tag; download again.", error=True)
                    off = page.time - time.time()
                    if abs(off) > M.CLOCK_TOLERANCE_S:
                        self.log(f"{address}: tag clock is off by {off:+.0f} s. Press 'Set clock' "
                                 "(records already stored keep their times).", error=True)
                finished()
            self.radio.run_on_tag(address, fn, done)
        return step

    # -- clock --
    def _set_clock(self) -> None:
        sel = self._selected()
        if not sel:
            return

        def step_for(address):
            def step(finished):
                self.status.config(text=f"Setting the clock of {address}...")

                def done(res, err):
                    if err:
                        self.log(f"{address}: set clock failed: {err}", error=True)
                    else:
                        self.log(f"{address}: clock set to {iso(res)} UTC")
                    finished()
                self.radio.run_on_tag(address, lambda t: t.set_time(), done)
            return step
        self._queue([step_for(a) for a in sel])

    # -- details --
    def _details(self) -> None:
        sel = self._selected()
        if not sel:
            return
        address = sel[0]
        self._set_busy(True, f"Reading {address}...")

        def done(info, err):
            self._set_busy(False)
            if err:
                self.log(f"{address}: {err}", error=True)
                return
            lines = [f"Tag {info.address}", f"Firmware {info.firmware}",
                     f"Clock {iso(info.time)} UTC ({info.time - int(time.time()):+d} s vs this computer)",
                     f"Log: {info.page.pending} record(s) waiting, {info.page.overwritten} overwritten "
                     "(lifetime, log full)", "", "Settings:"]
            for s in S.SETTINGS:
                raw = info.config.get(P.REGS.get(s.reg, ""), None)
                if raw is not None:
                    lines.append(f"  {s.label}: {s.to_display(raw)} {s.unit}".rstrip())
            lines += ["", "Counters:"]
            for k, v in info.stats.items():
                lines.append(f"  {k}: {P.reset_cause_text(v) if k == 'reset_cause' else v}")
            win = tk.Toplevel(self.root)
            win.title(f"{address} details")
            txt = ScrolledText(win, width=70, height=30)
            txt.insert("end", "\n".join(lines))
            txt.configure(state="disabled")
            txt.pack(fill="both", expand=True)
        self.radio.run_on_tag(address, lambda t: t.info(), done)

    # -- about --
    def _about(self) -> None:
        from . import COPYRIGHT, CONTACT, LICENSE, __version__
        notices = os.path.join(os.path.dirname(ASSETS), "THIRD-PARTY-NOTICES.md")
        text = (f"{TITLE}\n"
                f"proxtool {__version__}, for ProxTit BLE tags (firmware 02.00.x)\n\n"
                f"{COPYRIGHT}\n{LICENSE}\n{CONTACT}\n\n"
                "Uses open-source software under permissive licences: Python and Tkinter (PSF), "
                "bleak (MIT), pywinrt (MIT, Windows), dbus-fast (MIT, Linux), typing_extensions (PSF); "
                "for the USB NCP adapter pyBGAPI and the Silicon Labs API definition (zlib), pySerial (BSD). "
                f"Details: {notices}")
        messagebox.showinfo(f"About {TITLE}", text)

    # -- firmware update --
    def _update_firmware(self) -> None:
        from . import dfu
        sel = self._selected()
        if not sel:
            return
        if len(sel) > 1:
            messagebox.showinfo(TITLE, "Update one tag at a time: select a single tag.")
            return
        address = sel[0]
        path = filedialog.askopenfilename(title="Firmware update file",
                                          filetypes=[("Firmware update", "*.gbl"), ("All files", "*.*")],
                                          initialdir=self.prefs.get("fwdir") or os.path.expanduser("~"))
        if not path:
            return
        self.prefs["fwdir"] = os.path.dirname(path)
        M.save_prefs(self.prefs)
        try:
            with open(path, "rb") as f:
                data = f.read()
            info = dfu.check_gbl(data)
        except (OSError, ValueError) as e:
            messagebox.showerror(TITLE, f"{os.path.basename(path)}: {e}")
            return
        msg = (f"Update {address} to firmware {info.version or '(version unknown)'}?\n\n"
               f"File: {os.path.basename(path)} ({info.size // 1024} kB)\n\n"
               "The tag restarts; its settings and stored records are kept, but download it "
               "first to be safe. Keep the tag within a few metres of this computer until "
               "the update has finished (about 1-2 minutes). If it is interrupted, run the "
               "update again.")
        if not messagebox.askyesno(TITLE, msg, icon="warning"):
            return
        self._set_busy(True, f"Updating {address}...")

        def prog(stage, frac):
            self.inbox.put(lambda: (self.progress.config(value=100 * frac),
                                    self.status.config(text=f"{address}: {stage}")))

        def done(fw, err):
            self._set_busy(False)
            if err:
                self.log(f"{address}: firmware update failed: {err}. If the tag no longer appears "
                         "in the list, it waits in update mode: run the update again.", error=True)
                messagebox.showerror(TITLE, f"Firmware update failed:\n{err}")
            else:
                ok = info.version is None or info.version in fw
                self.log(f"{address}: firmware updated, the tag reports {fw}", error=not ok)
                if not ok:
                    messagebox.showwarning(TITLE, f"The tag reports {fw}, expected {info.version}.")
        self.radio.run_job(lambda: dfu.update(address, data, prog), done)

    # -- settings --
    def _settings(self) -> None:
        sel = self._selected()
        if not sel:
            return
        first = sel[0]
        self._set_busy(True, f"Reading the settings of {first}...")

        async def read(t):
            if await t.legacy():
                return await t.firmware()
            return {s.reg: await t.get_cfg(s.reg) for s in S.SETTINGS}

        def done(cur, err):
            self._set_busy(False)
            if err:
                self.log(f"{first}: {err}", error=True)
                return
            if isinstance(cur, str):
                messagebox.showinfo(TITLE, f"{first} runs firmware {cur}. Its settings differ from "
                                    "firmware 02.00 and are not changed here; update its firmware first "
                                    "(Download still works).")
                return
            SettingsDialog(self, sel, cur)
        self.radio.run_on_tag(first, read, done)

    def write_settings(self, addresses: List[str], wanted: Dict[int, int], current: Dict[int, int]) -> None:
        def step_for(address):
            def step(finished):
                self.status.config(text=f"Writing settings to {address}...")

                async def fn(t):
                    cur = {s.reg: await t.get_cfg(s.reg) for s in S.SETTINGS}
                    out = []
                    for reg, val in S.write_order(S.changed(cur, wanted), cur):
                        ok = await t.set_cfg(reg, val)
                        out.append((reg, val, ok, await t.get_cfg(reg)))
                    return out

                def done(res, err):
                    if err:
                        self.log(f"{address}: writing settings failed: {err}", error=True)
                    elif not res:
                        self.log(f"{address}: settings already as wanted")
                    else:
                        for reg, val, ok, now in res:
                            s = S.BY_REG[reg]
                            shown = f"{s.label} = {s.to_display(now)} {s.unit}".rstrip()
                            if not ok:
                                self.log(f"{address}: {s.label} REJECTED by the tag (still {s.to_display(now)})", error=True)
                            elif now != val:
                                self.log(f"{address}: {shown} (the tag adjusted {s.to_display(val)})")
                            else:
                                self.log(f"{address}: {shown}")
                    finished()
                self.radio.run_on_tag(address, fn, done)
            return step
        self._queue([step_for(a) for a in addresses])


class SettingsDialog:
    def __init__(self, app: App, addresses: List[str], current: Dict[int, int]):
        self.app, self.addresses, self.current = app, addresses, current
        w = self.win = tk.Toplevel(app.root)
        who = addresses[0] if len(addresses) == 1 else f"{len(addresses)} tags"
        w.title(f"Settings: {who}")
        w.transient(app.root)
        frm = ttk.Frame(w, padding=10)
        frm.pack(fill="both", expand=True)
        if len(addresses) > 1:
            ttk.Label(frm, text=f"Shown: the settings of {addresses[0]}. Saving writes them to all "
                                f"{len(addresses)} selected tags.", foreground="#555",
                      wraplength=app.px(560)).pack(anchor="w", pady=(0, 6))
        self.vars: Dict[int, tk.StringVar] = {}
        basic = ttk.LabelFrame(frm, text="Encounter settings", padding=8)
        basic.pack(fill="x")
        self.show_adv = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Show radio schedule settings", variable=self.show_adv,
                        command=self._toggle_adv).pack(anchor="w", pady=(8, 0))
        holder = ttk.Frame(frm)                 # keeps the place of the hidden frame
        holder.pack(fill="x")
        self.adv_frame = ttk.LabelFrame(holder, text="Radio schedule (detection vs battery)", padding=8)
        for s in S.SETTINGS:
            self._row(self.adv_frame if s.advanced else basic, s)
        ttk.Label(frm, text="Use the same settings on every tag of a study.", foreground="#555").pack(anchor="w", pady=(4, 0))
        bar = ttk.Frame(frm)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="Save", command=self._save).pack(side="right")
        ttk.Button(bar, text="Cancel", command=w.destroy).pack(side="right", padx=6)
        ttk.Button(bar, text="Defaults", command=self._defaults).pack(side="left")

    def _row(self, parent, s: S.Setting) -> None:
        r = ttk.Frame(parent)
        r.pack(fill="x", pady=2)
        ttk.Label(r, text=s.label, width=26).pack(side="left")
        v = tk.StringVar(value=s.to_display(self.current.get(s.reg, int(s.default * s.scale))))
        self.vars[s.reg] = v
        if s.choices is not None:
            ttk.Combobox(r, textvariable=v, values=list(s.choices.values()), state="readonly", width=12).pack(side="left")
        else:
            ttk.Entry(r, textvariable=v, width=14).pack(side="left")
        ttk.Label(r, text=s.unit, width=8).pack(side="left", padx=(4, 0))
        ttk.Label(parent, text=s.help, foreground="#555", wraplength=self.app.px(560),
                  justify="left").pack(anchor="w", padx=(12, 0))

    def _toggle_adv(self) -> None:
        if self.show_adv.get():
            self.adv_frame.pack(fill="x", pady=(4, 0))
        else:
            self.adv_frame.pack_forget()

    def _defaults(self) -> None:
        for s in S.SETTINGS:
            self.vars[s.reg].set(s.to_display(int(round(s.default * s.scale))))

    def _save(self) -> None:
        wanted, errors = {}, []
        for s in S.SETTINGS:
            raw, why = s.parse(self.vars[s.reg].get())
            if raw is None:
                errors.append(f"{s.label}: {why}")
            else:
                wanted[s.reg] = raw             # signed where the register is (TX power)
        if errors:
            messagebox.showerror("Settings", "\n".join(errors), parent=self.win)
            return
        diff = S.changed(self.current, wanted)
        if not diff and len(self.addresses) == 1:
            self.win.destroy()
            return
        msg = f"Write the settings to {len(self.addresses)} tag(s)?"
        if wanted.get(0x00) == 0 and self.current.get(0x00) != 0:
            msg += "\n\nMode Off: the tag stops logging and sleeps. To connect again, wake it with the magnet."
        if not messagebox.askyesno("Settings", msg, parent=self.win):
            return
        self.win.destroy()
        self.app.write_settings(self.addresses, wanted, self.current)


def _dpi_aware() -> None:
    """Sharp text on scaled Windows displays (125 %, 150 %, ...)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def main() -> None:
    _dpi_aware()
    root = tk.Tk()
    try:
        App(root)
    except SystemExit:
        return
    root.mainloop()


if __name__ == "__main__":
    main()
