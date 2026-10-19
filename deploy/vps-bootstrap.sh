#!/usr/bin/env bash
# One-time setup of a VPS for the studio connector. Adapted from green-harness
# deploy/vps-bootstrap.sh; run ONCE after Docker is installed, from a copy of deploy/, as a
# sudo user who logs in with an SSH key:
#
#   scp -r deploy/ you@vps:studio-deploy/
#   ssh you@vps
#   sudo STUDIO_DOMAIN=studio.greenflac.online VPS_PUBLIC_HOST=<IP GitHub connects to> \
#        ACME_EMAIL=you@example.com STUDIO_LAYOUT=own|harness bash studio-deploy/vps-bootstrap.sh
#
# STUDIO_LAYOUT: `own` = this compose runs its own Caddy on 80/443 (COMPOSE_PROFILES=tls);
# `harness` = the VPS already runs the harness Caddy on 80/443 and serves the studio site
# block (deploy/Caddyfile.harness-site), so this compose publishes the server on the loopback
# only. Default: `harness` when /srv/harness exists, else `own`.
#
# Idempotent: a second run never regenerates a secret or the deploy key. It does:
#   1. the `studio` user (docker group) and /srv/studio with the deploy files, ROOT-owned
#   2. secret files, mode 600, owned by the server's uid 10002: the key pepper (random) and
#      an empty vendor.env the owner fills (GEMINI_API_KEY=..., docs/CONNECTOR.md)
#   3. ufw, when it is active: 80 and 443 in (own layout only)
#   4. the deploy key: generated here, authorised for `studio` with a forced command
#      (release.sh) and `restrict`; the private half is printed ONCE for GitHub, then deleted
#   5. prints the GitHub secrets to add
# SSH hardening, unattended upgrades and fail2ban are NOT repeated here: on the harness VPS
# the harness bootstrap did them; on a fresh VPS run those steps first (docs/CONNECTOR.md).
set -Eeuo pipefail
trap 'echo "vps-bootstrap: stopped at line $LINENO with exit $? - nothing after it ran" >&2' ERR

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR=/srv/studio
SECRETS_DIR="$HOME_DIR/secrets"
DEPLOY_USER=studio
SERVER_UID=10002
DEPLOY_FILES=(compose.yaml Caddyfile release.sh probe.sh .env.example)
KEY_MARK="studio-deploy"

die() { echo "vps-bootstrap: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run with sudo"
command -v docker >/dev/null || die "docker is not installed (https://docs.docker.com/engine/install/)"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is not installed"
DOMAIN="${STUDIO_DOMAIN:-}"
[[ $DOMAIN =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] \
  || die "STUDIO_DOMAIN '$DOMAIN' is not a plain lowercase host name"
PUBLIC_HOST="${VPS_PUBLIC_HOST:-}"
[ -n "$PUBLIC_HOST" ] || die "VPS_PUBLIC_HOST is required: the IP or name GitHub Actions connects to"
LAYOUT="${STUDIO_LAYOUT:-}"
if [ -z "$LAYOUT" ]; then
  if [ -d /srv/harness ]; then LAYOUT=harness; else LAYOUT=own; fi
fi
case "$LAYOUT" in
  own) PROFILES=tls ;;
  harness) PROFILES= ;;
  *) die "STUDIO_LAYOUT must be own or harness" ;;
esac
if [ "$LAYOUT" = own ]; then
  [ -n "${ACME_EMAIL:-}" ] || die "ACME_EMAIL is required with its own Caddy (Let's Encrypt)"
fi

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
  sed -e "s/^STUDIO_DOMAIN=.*/STUDIO_DOMAIN=$DOMAIN/" \
      -e "s/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=$PROFILES/" \
      -e "s/^ACME_EMAIL=.*/ACME_EMAIL=${ACME_EMAIL:-unused@example.com}/" \
      "$HERE/.env.example" > "$HOME_DIR/.env"
  chown root:"$DEPLOY_USER" "$HOME_DIR/.env"
  chmod 0644 "$HOME_DIR/.env"
  echo "[done] .env written for $DOMAIN, layout $LAYOUT"
else
  echo "[kept] $HOME_DIR/.env exists; edit it as root to change the domain or layout"
fi

# - 2. secrets: files, never variables (green-harness config.secret) -
if [ ! -s "$SECRETS_DIR/key_pepper" ]; then
  ( umask 077; head -c 48 /dev/urandom | base64 | tr -d '\n=' > "$SECRETS_DIR/key_pepper" )
  echo "[done] key pepper generated"
fi
[ -e "$SECRETS_DIR/vendor.env" ] || ( umask 077; : > "$SECRETS_DIR/vendor.env" )
chown "$SERVER_UID:$SERVER_UID" "$SECRETS_DIR/key_pepper" "$SECRETS_DIR/vendor.env"
chmod 0600 "$SECRETS_DIR/key_pepper" "$SECRETS_DIR/vendor.env"

# - 3. firewall -
if [ "$LAYOUT" = own ] && command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null
  echo "[done] ufw: 80 and 443 open"
fi

# - 4. deploy key, generated last -
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
  echo "[done] deploy key generated and authorised (forced command release.sh)"
fi

# - 5. what the owner adds to GitHub -
SSH_PORT=$(sshd -T 2>/dev/null | sed -n 's/^port //p' | head -n 1)
SSH_PORT=${SSH_PORT:-22}
KNOWN_HOSTS=$(ssh-keyscan -p "$SSH_PORT" -t ed25519 127.0.0.1 2>/dev/null \
  | sed "s/^[^ ]*/$( [ "$SSH_PORT" = 22 ] && echo "$PUBLIC_HOST" || echo "[$PUBLIC_HOST]:$SSH_PORT" )/" | head -n 1)
cat <<EOF

==========================================================================================
GitHub: repository greenflac/lipsync-templates -> Settings -> Environments -> "connector"
-> Environment secrets. Add exactly these five:

  VPS_HOST         $PUBLIC_HOST
  VPS_PORT         $SSH_PORT
  VPS_USER         $DEPLOY_USER
  VPS_KNOWN_HOSTS  $KNOWN_HOSTS
EOF
if [ -n "$PRIVATE_KEY" ]; then
  cat <<EOF
  VPS_SSH_KEY      the whole block below, BEGIN and END lines included. Shown ONCE:
$PRIVATE_KEY
EOF
else
  echo "  VPS_SSH_KEY      (given at the first run; to replace it, delete the line ending in"
  echo "                   '$KEY_MARK' in $SSH_DIR/authorized_keys and rerun)"
fi
cat <<EOF

Environment variable (same environment -> Variables): STUDIO_DOMAIN = $DOMAIN
DNS: an A record $DOMAIN -> this machine's public IPv4, before the first deploy.
Layout: $LAYOUT$( [ "$LAYOUT" = harness ] && echo " - add deploy/Caddyfile.harness-site to the harness Caddy (docs/CONNECTOR.md)" )
Vendor keys (optional, for search_web and probe_model_limit): NAME=value lines in
  $SECRETS_DIR/vendor.env (edit as root; the server reads it at start).
==========================================================================================
EOF
