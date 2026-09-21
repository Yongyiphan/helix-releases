#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo." >&2; exit 1; fi
purge=0
if [ "${1-}" = "--purge-state" ]; then purge=1; elif [ "${1-}" != "" ]; then echo "usage: $0 [--purge-state]" >&2; exit 2; fi
for service in hdc-controller.service helix-updater.service helix-updater-dev.service; do systemctl stop "$service" 2>/dev/null || true; systemctl disable "$service" 2>/dev/null || true; done
rm -f /etc/systemd/system/hdc-controller.service /etc/systemd/system/helix-updater.service /etc/systemd/system/helix-updater-dev.service
systemctl daemon-reload 2>/dev/null || true
rm -f /usr/local/bin/hr /usr/local/bin/hdc /usr/local/bin/helix-updater
rm -rf /opt/helix/production/helix-releases /opt/helix/production/hdc /opt/helix/production/updater \
    /opt/helix/development/updater /usr/local/libexec/helix-development \
    /opt/helix/helix-releases /opt/helix/hdc /opt/helix/updater \
    /var/cache/helix/production/updater /var/cache/helix/development/updater \
    /var/cache/helix/updater /var/log/helix/production /var/log/helix/development \
    /var/log/helix/hdc /var/log/helix/updater
if [ "$purge" -eq 1 ]; then
    rm -rf /var/lib/helix/hdc /var/lib/helix/updater \
        /var/lib/helix/production/updater /var/lib/helix/development/updater
    rm -f /etc/helix/helix-updater.toml /etc/helix/helix-updater.toml.pre-profiles
    rm -rf /etc/helix/hdc /etc/helix/updater
fi
echo "Helix binaries and services removed; state and machine-local configuration were $([ "$purge" -eq 1 ] && echo purged || echo preserved)."
