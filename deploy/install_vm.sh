#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  printf 'Run with sudo: sudo /opt/yobi/current/deploy/install_vm.sh\n' >&2
  exit 1
fi

dnf install -y nginx python3.9 python3.9-pip tar
id yobi >/dev/null 2>&1 || useradd --system --home-dir /opt/yobi --shell /sbin/nologin yobi
install -d -o yobi -g yobi -m 0755 /opt/yobi/releases /opt/yobi/shared
install -d -o root -g yobi -m 0750 /etc/yobi

if [[ ! -x /opt/yobi/venv/bin/python ]]; then
  python3.9 -m venv /opt/yobi/venv
fi
/opt/yobi/venv/bin/python -m pip install --upgrade pip
/opt/yobi/venv/bin/python -m pip install -e '/opt/yobi/current/backend'

install -o root -g root -m 0644 /opt/yobi/current/deploy/systemd/yobi-api.service /etc/systemd/system/yobi-api.service
install -o root -g root -m 0644 /opt/yobi/current/deploy/nginx/nginx.conf /etc/nginx/nginx.conf
install -o root -g root -m 0644 /opt/yobi/current/deploy/nginx/yobi.conf /etc/nginx/conf.d/yobi.conf
rm -f /etc/nginx/conf.d/default.conf

if command -v getsebool >/dev/null 2>&1 && command -v setsebool >/dev/null 2>&1; then
  if getsebool httpd_can_network_connect | grep -q -- '--> off'; then
    setsebool -P httpd_can_network_connect on
  fi
fi

if systemctl is-active --quiet firewalld; then
  if ! firewall-cmd --quiet --query-service=http; then
    firewall-cmd --permanent --add-service=http
    firewall-cmd --reload
  fi
fi

systemctl daemon-reload
nginx -t
systemctl enable nginx yobi-api
printf 'VM packages and services are installed. Run the secure bootstrap before starting YOBI.\n'
