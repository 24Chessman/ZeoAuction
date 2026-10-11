#!/bin/sh
# Provision the dedicated load-test host (owner: Ayush, support for #23 and Plan 7 #24-#26).
# Target: 8 vCPU / 16 GB, Ubuntu 22.04 or 24.04, this repository checked out. Run as a sudoer:
#
#   sh infra/loadtest/provision.sh                # install, tune, start the stack, seed, print ids
#   sh infra/loadtest/provision.sh --no-install   # Docker already present
#   sh infra/loadtest/provision.sh --seed-only    # 50 fresh auctions before another sweep
#
# The load generator runs on a SECOND machine on the same network, so it never competes with
# the services for CPU (infra/loadtest/README.md).
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL=1
SEED_ONLY=0
case "${1:-}" in
  --no-install) INSTALL=0 ;;
  --seed-only) SEED_ONLY=1 ;;
esac

say() { printf '\n==> %s\n' "$*"; }

seed_auctions() {
  say "Seeding 50 fresh OPEN auctions"
  docker compose cp infra/loadtest/seed-auctions.sql postgres:/tmp/seed-auctions.sql
  docker compose exec -T postgres psql -U postgres -d zeoauction -At -v ON_ERROR_STOP=1 \
    -f /tmp/seed-auctions.sql | grep -E '^[0-9a-f-]{36}$' > "$ROOT/infra/loadtest/ids.txt"
  echo "$(wc -l < "$ROOT/infra/loadtest/ids.txt") auction ids in infra/loadtest/ids.txt"
}

if [ "$SEED_ONLY" -eq 1 ]; then
  cd "$ROOT"
  seed_auctions
  exit 0
fi

if [ "$INSTALL" -eq 1 ]; then
  say "Installing Docker Engine and the compose plugin"
  sudo apt-get update -y
  sudo apt-get install -y ca-certificates curl
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
fi

say "Kernel and limits for many short-lived connections"
sudo tee /etc/sysctl.d/90-zeo-loadtest.conf >/dev/null <<'EOF'
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096
net.ipv4.ip_local_port_range = 10240 65535
net.ipv4.tcp_tw_reuse = 1
fs.file-max = 1048576
vm.overcommit_memory = 1
EOF
sudo sysctl --system >/dev/null
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/limits.conf >/dev/null <<'EOF'
[Service]
LimitNOFILE=1048576
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker

if command -v cpupower >/dev/null 2>&1; then
  say "CPU governor: performance (steadier numbers)"
  sudo cpupower frequency-set -g performance || true
fi

say "Recording the host for the report"
{
  echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "kernel: $(uname -r)"
  echo "cpus: $(nproc)"
  echo "memory: $(free -h | awk '/Mem:/ {print $2}')"
  echo "cpu: $(lscpu | awk -F: '/Model name/ {gsub(/^ +/, "", $2); print $2}')"
  echo "commit: $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
} | tee "$ROOT/infra/loadtest/host-info.txt"

say "Starting the stack (services built one at a time to keep memory in check)"
cd "$ROOT"
for service in $(docker compose config --services); do
  docker compose build "$service" >/dev/null
done
docker compose up -d
# Wait until no container is still starting or unhealthy.
while docker compose ps --format '{{.Health}}' | grep -Eq 'starting|unhealthy'; do
  sleep 5
done
docker compose ps

say "Seeding the development accounts"
docker compose exec -T postgres psql -U postgres -d zeoauction -v ON_ERROR_STOP=1 \
  -f /seed/dev-seed.sql >/dev/null
seed_auctions

say "Ready. From the load-generator machine:"
cat <<EOF
  python tests/load/aggregate_rig.py --mode http --base-url http://$(hostname -I | awk '{print $1}'):8004 \\
      --auction-ids ids.txt --sweep 250,500,750,1000,1250 --duration 30 --markdown
Fresh auctions before every sweep: sh infra/loadtest/provision.sh --seed-only
EOF
