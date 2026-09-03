# Troubleshooting

Camera absent: `lsusb | grep -i 04a9:32d9`; check power, Auto Power Off, cable and port. Camera visible but unavailable: run `aag-canon-diagnose`; the manager normally handles GVFS. AF fails: lens switch must be AF. Manual exposure controls unavailable: automatic/Green mode is valid; use M only for manual exposure. Stale manager: `aag-canon-stop && aag-canon`. Do not disable GVFS or USB autosuspend globally, reset the whole USB controller, change kernels solely for this camera, or run the GUI with sudo without new evidence.
