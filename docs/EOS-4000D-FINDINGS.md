# EOS 4000D Findings

- USB VID:PID: `04a9:32d9`, PTP still-image interface.
- Full disappearance from `lsusb` was camera-side **Auto Power Off**, not Linux runtime autosuspend. Fix: disable Auto Power Off in the camera menu.
- GNOME `gvfsd-gphoto2` can cause `Could not claim interface 0`; targeted Canon unmount fixes ownership without disabling GVFS globally.
- Generic capture produced `0x2019` in early tests; Canon `Press Full -> Release Full` was reliable and is the production capture path.
- v1.0 ~2 FPS was app-side pacing; v1.1 physically measured about 27.6 FPS, 37 ms acquisition, 31 ms UI.
- MF was only a diagnostic baseline. AF Once is physically validated with the lens switch on AF.
