# Canon EOS 4000D Linux Tether

A native Ubuntu/Linux tethering manager for the **Canon EOS 4000D** using **libgphoto2**.

> Project name in the UI: **AAG Canon EOS 4000D Linux Manager**

## Features

- Live View (validated at ~27.6 FPS on the development EOS 4000D)
- AF Once autofocus
- Remote capture and automatic download
- USB disconnect/reconnect recovery
- Targeted GNOME/GVFS handling
- Persistent libgphoto2 session
- Atomic `.part` download/rename
- No root GUI
- No global USB/kernel hacks
- Does not delete images from the camera

## Tested camera

- **Canon EOS 4000D** — USB `04a9:32d9`

Other Canon cameras may work through libgphoto2, but are **not claimed as supported** until physically validated.

## Quick install

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

Download `dist/canon-eos-4000d-linux-installer.run`, then:

```bash
chmod +x canon-eos-4000d-linux-installer.run
./canon-eos-4000d-linux-installer.run
```

The one-file installer clones the current public release and runs the verified installer.

## Important camera settings

- **Auto Power Off = Disable** is required for stable tethering.
- Lens **AF** is required only for **AF Once**.
- **M mode is optional** and is only needed when you want manual exposure controls.
- Automatic/Green exposure mode remains valid for Live View and capture.

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

## What was solved

The project documents the practical EOS 4000D issues found during physical testing: camera-side Auto Power Off causing full USB disappearance, GNOME/GVFS PTP contention, reliable Canon remote-release capture, Live View queue/pacing optimization, autofocus cleanup, and reconnect behavior.

See [Architecture](docs/ARCHITECTURE.md), [Troubleshooting](docs/TROUBLESHOOTING.md), [EOS 4000D findings](docs/EOS-4000D-FINDINGS.md), and [Source integrity](docs/SOURCE-INTEGRITY.md).

## Safety / system impact

The installer does **not** disable GVFS globally, disable USB autosuspend globally, change the kernel, install a boot service, run the GUI as root, delete camera images, or run `apt autoremove`.

## License

MIT. See [LICENSE](LICENSE).
