#!/usr/bin/env bash
# One-time setup of the studio connector on the green-harness VPS (owner decision 2026-10-19).
# Adapted from green-harness deploy/vps-bootstrap.sh. Run ONCE, after the harness has been
# redeployed with REVISION 10 (that creates the network harness-studio-edge), from a copy of
# deploy/, as the same sudo user who runs the harness bootstrap:
#
#   scp -r deploy/ you@vps:studio-deploy/
#   ssh you@vps
#   sudo VPS_PUBLIC_HOST=<the VPS_HOST value of the harness> bash studio-deploy/vps-bootstrap.sh
#
# Idempotent: a second run never regenerates a secret or the deploy key. It does:
#   1. the `studio` user (docker group) and /srv/studio with the deploy files, ROOT-owned
#      (release.sh refuses to run from files its caller can change)
#   2. secret files, mode 600, owned by the server's uid 10002: the key pepper (random) and
#      an empty vendor.env the owner fills
#   3. the deploy key: generated here and authorised for `studio` only, with a forced command
#      (/srv/studio/release.sh) and `restrict`. The harness deploy key and its forced command
#      are NOT touched. The private half is printed ONCE for GitHub, then deleted.
#   4. prints the GitHub secrets to add to greenflac/lipsync-templates
# There is no Caddy, ufw, sshd or fail2ban step. The harness bootstrap did those, and its Caddy
# serves studio.greenflac.online.
set -Eeuo pipefail
trap 'echo "vps-bootstrap: stopped at line $LINENO with exit $? - nothing after it ran" >&2' ERR

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR=/srv/studio
SECRETS_DIR="$HOME_DIR/secrets"
DEPLOY_USER=studio
SERVER_UID=10002
DEPLOY_FILES=(compose.yaml release.sh probe.sh .env.example)
KEY_MARK="studio-deploy"
NETWORK=harness-studio-edge

die() { echo "vps-bootstrap: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run with sudo"
command -v docker >/dev/null || die "docker is not installed"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is not installed"
PUBLIC_HOST="${VPS_PUBLIC_HOST:-}"
[ -n "$PUBLIC_HOST" ] || die "VPS_PUBLIC_HOST is required: the harness's VPS_HOST value"
docker network inspect "$NETWORK" >/dev/null 2>&1 \
  || die "docker network $NETWORK does not exist: redeploy the harness with REVISION 10 first (green_harness RUNBOOK section 14)"

# - 1. user and files -
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "/home/$DEPLOY_USER" --shell /bin/bash "$DEPLOY_USER"
fi
usermod -aG docker "$DEPLOY_USER"
install -d -o root -g "$DEPLOY_USER" -m 0750 "$HOME_DIR"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0700 "$HOME_DIR/state"
install -d -o root -g root -m 0711 "$SECRETS_DIR"
for name in "${DEPLOY_FILES[@]}"; do
  mode=0644
  case "$name" in *.sh) mode=0755 ;; esac
  install -o root -g "$DEPLOY_USER" -m "$mode" "$HERE/$name" "$HOME_DIR/$name"
done
if [ ! -f "$HOME_DIR/.env" ]; then
  # The harness Caddy's address, for release.sh's probe (b-292: not always the loopback).
  probe_ip=$(sed -n 's/^HARNESS_BIND_IP=//p' /srv/harness/.env 2>/dev/null | tail -n 1 | tr -d "\"'")
  case "$probe_ip" in "" | 0.0.0.0) probe_ip=127.0.0.1 ;; esac
  sed -e "s/^STUDIO_PROBE_IP=.*/STUDIO_PROBE_IP=$probe_ip/" "$HERE/.env.example" > "$HOME_DIR/.env"
  chown root:"$DEPLOY_USER" "$HOME_DIR/.env"
  chmod 0644 "$HOME_DIR/.env"
  echo "[done] .env written (probe address $probe_ip)"
else
  echo "[kept] $HOME_DIR/.env exists; edit it as root to change it"
fi

# - 2. secrets: files, never variables (green-harness config.secret) -
if [ ! -s "$SECRETS_DIR/key_pepper" ]; then
  ( umask 077; head -c 48 /dev/urandom | base64 | tr -d '\n=' > "$SECRETS_DIR/key_pepper" )
  echo "[done] key pepper generated"
fi
[ -e "$SECRETS_DIR/vendor.env" ] || ( umask 077; : > "$SECRETS_DIR/vendor.env" )
chown "$SERVER_UID:$SERVER_UID" "$SECRETS_DIR/key_pepper" "$SECRETS_DIR/vendor.env"
chmod 0600 "$SECRETS_DIR/key_pepper" "$SECRETS_DIR/vendor.env"

# - 3. deploy key, generated last -
SSH_DIR="/home/$DEPLOY_USER/.ssh"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0700 "$SSH_DIR"
touch "$SSH_DIR/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "$SSH_DIR/authorized_keys"
chmod 0600 "$SSH_DIR/authorized_keys"
PRIVATE_KEY=""
if grep -q " $KEY_MARK\$" "$SSH_DIR/authorized_keys"; then
  echo "[kept] deploy key already authorised (the private half is not shown again)"
else
  keydir=$(mktemp -d)
  trap 'rm -rf "$keydir"' EXIT
  ssh-keygen -q -t ed25519 -N '' -C "$KEY_MARK" -f "$keydir/key"
  PRIVATE_KEY=$(cat "$keydir/key")
  printf 'restrict,command="%s/release.sh" %s\n' "$HOME_DIR" "$(cat "$keydir/key.pub")" \
    >> "$SSH_DIR/authorized_keys"
  rm -rf "$keydir"
  echo "[done] deploy key generated and authorised for $DEPLOY_USER (forced command release.sh)"
fi

# - 4. what the owner adds to GitHub -
SSH_PORT=$(sshd -T 2>/dev/null | sed -n 's/^port //p' | head -n 1)
SSH_PORT=${SSH_PORT:-22}
cat <<EOF

==========================================================================================
GitHub: repository greenflac/lipsync-templates -> Settings -> Environments -> "connector"
-> Environment secrets. The same five NAMES as the harness's "production" environment:

  VPS_HOST         $PUBLIC_HOST          (same value as the harness's)
  VPS_PORT         $SSH_PORT          (same value as the harness's)
  VPS_KNOWN_HOSTS  the harness's VPS_KNOWN_HOSTS value, unchanged (same machine, same host key)
  VPS_USER         $DEPLOY_USER          (NOT harness)
EOF
if [ -n "$PRIVATE_KEY" ]; then
  cat <<EOF
  VPS_SSH_KEY      NEW - the whole block below, BEGIN and END lines included. Shown ONCE:
$PRIVATE_KEY
EOF
else
  echo "  VPS_SSH_KEY      (given at the first run; to replace it, delete the line ending in"
  echo "                   '$KEY_MARK' in $SSH_DIR/authorized_keys and rerun)"
fi
cat <<EOF

Environment variable (same environment -> Variables): STUDIO_DOMAIN = studio.greenflac.online
Vendor keys (optional, for search_web and probe_model_limit): NAME=value lines in
  $SECRETS_DIR/vendor.env (edit as root; the server reads it at start).
==========================================================================================
EOF
