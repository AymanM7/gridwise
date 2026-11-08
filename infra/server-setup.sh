#!/usr/bin/env bash
# One-time Vultr VM setup (Ubuntu 22.04/24.04). Run as root:  bash server-setup.sh
# Installs Docker + Compose, opens the firewall for SSH/HTTP/HTTPS, adds 2 GB swap
# (Next.js builds need it on 1 GB plans), and creates /opt/gridwise.
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

if command -v ufw >/dev/null 2>&1; then
  ufw allow OpenSSH >/dev/null
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
  ufw allow 443/udp >/dev/null
  ufw --force enable >/dev/null
fi

if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

mkdir -p /opt/gridwise
echo "server ready: $(docker --version)"
