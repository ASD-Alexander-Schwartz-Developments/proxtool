# Command Line

`proxtool` does everything the window does, for scripts and remote computers.
`proxtool -h` and `proxtool <command> -h` list the options.

| Command | Does |
|---|---|
| `proxtool scan` | List tags in range: mode, battery, records, clock, flags |
| `proxtool monitor [TAG]` | Print every beacon as it arrives |
| `proxtool info TAG` | Firmware, clock offset, settings, log state, counters |
| `proxtool settime TAG` | Set the tag clock (UTC) |
| `proxtool getcfg TAG` | All settings |
| `proxtool setcfg TAG NAME VALUE` | One setting, by name (`silence_gap_s`) or number (`0x0A`) |
| `proxtool download TAG [-o DIR]` | Download to `DIR/<tag>.csv` |
| `proxtool gateway [-o DIR]` | Keep collecting from every tag in range ([Automatic Collection](Automatic-Collection)) |
| `proxtool update TAG FILE.gbl --yes` | Firmware update |
| `proxtool release TAG MS --yes` | Pulse the drop-off release output for MS milliseconds |
| `proxtool gui` | Open the window |

Options before the command:

| Option | Meaning |
|---|---|
| `--via ble` | the computer's Bluetooth (default) |
| `--via ncp` / `--via ncp:PORT` | a USB NCP adapter ([Reaching Tags](Reaching-Tags)) |
| `--legacy-local-time` | firmware 01.02.x tags: set local time instead of UTC ([Older Firmware](Older-Firmware)) |

The environment variable `PROXTOOL_VIA` sets the default radio.

Examples:

```
proxtool scan
proxtool --via ncp:COM7 download C0:FF:EE:00:10:01 -o D:\Study-2026\ProxTit
proxtool setcfg C0:FF:EE:00:10:01 silence_gap_s 60
proxtool --via ncp gateway -o D:\Study-2026\ProxTit
```

The `bench` and `pair-check` commands are for ASD's firmware testing with a
peer simulator; see [For Developers](For-Developers).
