# For Developers

**Source:** <https://github.com/ASD-Alexander-Schwartz-Developments/proxtool>
(Apache-2.0). Python 3.9+, no compiled parts.

```
git clone https://github.com/ASD-Alexander-Schwartz-Developments/proxtool
cd proxtool
pip install -e ".[ncp]"
python -m unittest discover -s tests      # no radio needed
```

## Layout

| Module | Role |
|---|---|
| `protocol.py` | Wire format: beacon, commands, records (no radio) |
| `link.py` | **Transport interface**: scan, connect, read/write characteristics; selection (`--via`) and plugin discovery |
| `ble.py` | Transport "ble": the computer's Bluetooth (bleak) |
| `ncp.py` | Transport "ncp": a Silicon Labs NCP adapter (pyBGAPI) |
| `tag.py` | Tag commands over any transport, firmware 01.02.x included |
| `dfu.py` | Firmware update (Silicon Labs AppLoader OTA) |
| `gui.py`, `model.py`, `settings.py` | The window; what it shows; the settings' labels, limits and help |
| `cli.py` | The command line |
| `scenario.py`, `verify.py` | Bench test against ASD's peer simulator |

## The protocol

[docs/ble-protocol.md](https://github.com/ASD-Alexander-Schwartz-Developments/proxtool/blob/main/docs/ble-protocol.md)
is the normative description of what a tag says over Bluetooth: beacon, control
point, settings registers, clock, download with acknowledgements, markers,
release trigger, firmware update and the differences in firmware 01.02.x. Any
program can implement it.

## Adding a radio (transport plugins)

A transport reaches tags some other way, e.g. ASD's future **RoostBox**
communicator. It is a class with the methods of `link.Transport` (`start_scan`,
`stop_scan`, `connect` returning a `link.Link` with `has`/`read`/`write`/`close`).
Another package registers it, without changing proxtool:

```toml
# pyproject.toml of the plugin package
[project.entry-points."proxtool.transports"]
roostbox = "proxtool_roostbox:RoostBoxTransport"
```

Then `proxtool --via roostbox:<option> ...` uses it; `<option>` arrives as the
`port` keyword. A plugin may be closed source; Apache-2.0 allows that.
`ncp.py` is a complete example.

## Tests and bench

`tests/` runs without hardware, including the NCP transport against a stand-in
adapter (`tests/test_ncp.py`). The `bench` commands check a tag's log against the
fixed scenario that ASD's peer simulator (closed firmware) plays; two tests that
compare against the firmware sources are skipped outside ASD.

## Releases

A tag `vX.Y.Z` builds the ready-made programs for Windows and Linux
(PyInstaller, `packaging/`) and attaches them to a GitHub release, as plain zips
and as VesperApp plugin packs (`plugin.json` of kind "tool"). The wiki is
published from `docs/wiki` with the same tag. See
[docs/vesperapp-addon.md](https://github.com/ASD-Alexander-Schwartz-Developments/proxtool/blob/main/docs/vesperapp-addon.md).
