#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo." >&2; exit 1; fi
purge=0
if [ "${1-}" = "--purge-state" ]; then purge=1; elif [ "${1-}" != "" ]; then echo "usage: $0 [--purge-state]" >&2; exit 2; fi
for service in hdc-controller.service helix-updater.service; do systemctl stop "$service" 2>/dev/null || true; systemctl disable "$service" 2>/dev/null || true; done
rm -f /etc/systemd/system/hdc-controller.service /etc/systemd/system/helix-updater.service
systemctl daemon-reload 2>/dev/null || true
rm -f /usr/local/bin/hr /usr/local/bin/hdc /usr/local/bin/helix-updater
rm -rf /opt/helix/helix-releases /opt/helix/hdc /opt/helix/updater /etc/helix/hdc /etc/helix/updater /var/cache/helix/updater /var/log/helix/hdc /var/log/helix/updater
if [ "$purge" -eq 1 ]; then rm -rf /var/lib/helix/hdc /var/lib/helix/updater; fi
echo "Helix installations removed; state was $([ "$purge" -eq 1 ] && echo purged || echo preserved)."
