# proxtool

PC tool for ProxTit BLE tags (firmware **02.00.x**) and the bench peer simulator.
Uses the laptop's own Bluetooth LE through [bleak](https://github.com/hbldh/bleak)
(Windows 10/11, macOS, Linux).

```sh
pip install bleak
pip install -e Host/proxtool          # gives the `proxtool` command (or: python -m proxtool)
```

| Command | Does |
|---|---|
| `proxtool scan` | List tags (mode, battery, records waiting, clock, flags) and simulators in range |
| `proxtool monitor [ADDR]` | Print every beacon as it arrives |
| `proxtool info ADDR` | Firmware, clock vs this PC, config, log state, GETSTATS counters |
| `proxtool settime ADDR` | Set the tag clock from this PC (UTC) |
| `proxtool getcfg ADDR` / `setcfg ADDR REG VALUE` | Config registers, by name (`silence_gap_s`) or number (`0x0A`) |
| `proxtool download ADDR [-o DIR]` | Download the log to `DIR/<address>.csv`; each batch is written to disk before it is acknowledged, so a broken link loses nothing |
| `proxtool release ADDR MS --yes` | Pulse the drop-off output |
| `proxtool bench start ADDR... [--clear]` | Find the simulator, write the bench config and clock to the tags, save `bench_session.json` |
| `proxtool bench check` | Download the tags and compare with the simulator scenario: PASS / FAIL with the missing and unexpected encounters |
| `proxtool pair-check A.csv ADDR_A B.csv ADDR_B` | Two real tags: did each log the other at the same times |

CSV columns: `seq, start_unix, start_utc, duration_s, peer, rssi, tx_power, type,
detail`. `type` is `marker` for BOOT / TIMESET / POWEROFF / START records (see
`Proxtit/docs/ble_download_protocol.md`). A record downloaded twice (an ack that
never reached the tag) has the same `seq`; readers keep one.

The bench procedure is in [docs/bench-test-plan.md](../../docs/bench-test-plan.md).

## Tests

```sh
cd Host/proxtool && python -m unittest discover -s tests
```

No radio needed: they cover the wire format, the scenario (checked against
`Proxtit/peersim.c`) and the bench verifier.
