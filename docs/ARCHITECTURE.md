# Architecture

One persistent libgphoto2 session; all camera I/O serialized in one worker. Targeted Canon GVFS release only. Live View uses in-memory `capture_preview()` and latest-frame coalescing. Capture uses Canon remote release, event/new-file detection, `.part` download and atomic rename. Reconnect is bounded. No root GUI, boot service, global USB policy change, or automatic deletion from the camera.
