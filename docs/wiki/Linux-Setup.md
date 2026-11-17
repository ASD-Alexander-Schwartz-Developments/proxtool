# Linux Setup

Linux support is by design and not yet verified on hardware. Reports are welcome
([issues](https://github.com/ASD-Alexander-Schwartz-Developments/proxtool/issues)).

**Ready-made program:** unzip `proxtool-<version>-linux-x64.zip` and run
`./ProxTitTags` or `./proxtool`. Make them executable first if needed
(`chmod +x ProxTitTags proxtool`).

**With Python:**

```
sudo apt install python3-pip python3-tk bluez
pip install "proxtool[ncp] @ git+https://github.com/ASD-Alexander-Schwartz-Developments/proxtool"
proxtool-gui
```

**The computer's Bluetooth** needs BlueZ 5.43 or later with `bluetoothd`
running (`systemctl status bluetooth`). If scanning is refused, add your user to
the `bluetooth` group and log in again.

**A USB NCP adapter** appears as `/dev/ttyACM0` (J-Link boards) or `/dev/ttyUSB0`
(CP210x). Your user needs access to it: add yourself to the `dialout` group
(`sudo usermod -aG dialout $USER`) and log in again. Then
`proxtool --via ncp:/dev/ttyACM0 scan`.
