# Getting Started

## Install

Pick one:

| Way | For | How |
|---|---|---|
| **Ready-made program** | most users | Download `proxtool-<version>-win-x64.zip` (or `-linux-x64`) from the [Releases page](https://github.com/ASD-Alexander-Schwartz-Developments/proxtool/releases), unzip it anywhere and start **ProxTitTags** (the window) or **proxtool** (the command line). No Python needed. |
| **From VesperApp** | VesperApp users | *Planned:* the Plugins tab of VesperApp will install and update ProxTit Tags and open it. Until then, use the ready-made program. |
| **With Python** | scripting, Linux, developers | Python 3.9 or later: `pip install "proxtool[ncp] @ git+https://github.com/ASD-Alexander-Schwartz-Developments/proxtool"`, then run `proxtool-gui` or `proxtool`. Leave out `[ncp]` if you never use a USB adapter. |

On Linux, see [Linux Setup](Linux-Setup) first.

## First run

1. Switch on the computer's Bluetooth, or plug in the USB adapter
   (see [Reaching Tags](Reaching-Tags)).
2. Start **ProxTit Tags**. Tags in range appear within a few seconds. A tag in
   **Off** mode does not advertise: wake it with the magnet.
3. Press **Change...** and choose the folder for the downloads. It is remembered.
4. Select tags and press **Download**, **Set clock** or **Settings...**. Ctrl-click
   or Shift-click selects several.

What the columns mean:

| Column | Meaning |
|---|---|
| Tag | The tag's id (its Bluetooth address). Other tags log it under this id. |
| Mode | `logger` (logging encounters), `off`, `modem` (add-on units). "log 90 % full": download soon. |
| Records | Records waiting on the tag. |
| Battery | As the tag reports it. *The reading is not yet calibrated: use it as a trend only.* |
| Clock | `ok`, `off by N s` or `NOT SET` (red). See [Clock](Clock). |
| Signal | Received signal strength of the tag's beacon at the computer. |
| Last heard | A tag not heard for 2 minutes leaves the list. |

The log at the bottom says what happened to each tag. Red lines need attention.
