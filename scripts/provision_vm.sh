#!/usr/bin/env bash
# provision_vm.sh — Oracle Always Free ARM Ubuntu 24.04
# Run once as the non-root user (ubuntu) after first SSH login.
# Usage: bash provision_vm.sh
set -euo pipefail

echo "==> Updating packages"
sudo apt-get update -q
sudo apt-get upgrade -y -q

echo "==> Installing Docker"
sudo apt-get install -y -q ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update -q
sudo apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "==> Adding ubuntu to docker group"
sudo usermod -aG docker ubuntu
echo "   (log out and back in, or run: newgrp docker)"

echo "==> Enabling Docker on boot"
sudo systemctl enable docker

echo "==> Installing git and other tools"
sudo apt-get install -y -q git make netfilter-persistent

echo "==> Flushing default Oracle iptables block rules"
sudo iptables -F
sudo iptables -X
sudo ip6tables -F
sudo ip6tables -X
sudo netfilter-persistent save

echo ""
echo "Done. Log out and back in so the docker group takes effect, then run deploy.sh."
