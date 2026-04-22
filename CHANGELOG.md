# Changelog

All notable changes to Cadge are documented here.

## Unreleased

### Fixed
- **`scripts/start.sh` and `scripts/stop.sh` no longer shell out to `lsof`**: macOS 26 (Darwin 25.2.0) has a reproducible kernel bug where `lsof` can trigger a NULL+0x48 data abort during proc/file-table iteration. The port-liveness check in `start.sh` now uses `nc -z 127.0.0.1 <port>`, and `stop.sh` discovers listener PIDs via `netstat -anv -p tcp` (which goes through PF_ROUTE sysctls, a different kernel path). Behavior is unchanged; only the underlying tool differs.
