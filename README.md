# Canon EOS 4000D Linux Tether

A native Ubuntu/Linux tethering manager for the **Canon EOS 4000D** using **libgphoto2**.

> Project name in the UI: **AAG Canon EOS 4000D Linux Manager**

## Features

- Live View (validated at ~27.6 FPS on the development EOS 4000D)
- AF Once autofocus
- Remote capture
- Automatic image download
- USB disconnect/reconnect recovery
- Targeted GNOME/GVFS handling
- Persistent libgphoto2 session
- No root GUI
- No global USB/kernel hacks
- Does not delete images from the camera

## Tested camera

- **Canon EOS 4000D** — USB `04a9:32d9`

Other Canon cameras may work through libgphoto2, but are **not claimed as supported** until physically validated.

## Ubuntu quick install

```bash
git clone https://github.com/aagprojectsteam-max/canon-eos-4000d-linux-tether.git
cd canon-eos-4000d-linux-tether
chmod +x install.sh
./install.sh
```

Then set on the camera:

**MENU → Setup → Auto power off → Disable**

Connect the camera, turn it on, and run:

```bash
aag-canon
```

## One-file installer

A standalone installer is included at:

```text
dist/canon-eos-4000d-linux-installer.run
```

Run:

```bash
chmod +x canon-eos-4000d-linux-installer.run
./canon-eos-4000d-linux-installer.run
```

## Important camera settings

- **Auto Power Off = Disable** is required for stable tethering.
- Lens **AF** is required only for the **AF Once** feature.
- **M mode is optional**. Use it only when you want manual exposure control.
- Automatic/Green exposure mode is valid for Live View and capture.

## Commands

```bash
aag-canon
aag-canon-status
aag-canon-diagnose
aag-canon-stop
```

Downloaded images are stored under:

```text
~/Pictures/Canon-4000D/YYYY-MM-DD/
```

## Why this project exists

Several existing Linux tethering applications were tested on the EOS 4000D but did not provide a reliable complete workflow. The working path was built directly on libgphoto2 and validated end-to-end on physical hardware.

See [Architecture](docs/ARCHITECTURE.md), [Troubleshooting](docs/TROUBLESHOOTING.md), and [EOS 4000D findings](docs/EOS-4000D-FINDINGS.md).

## Safety / system impact

The installer does **not**:

- disable GVFS globally;
- disable USB autosuspend globally;
- change the kernel;
- install a boot service;
- require the GUI to run as root;
- delete images from the camera;
- run `apt autoremove`.

## License

MIT. See [LICENSE](LICENSE).
