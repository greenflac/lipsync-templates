#!/usr/bin/env bash
# Releases the studio connector on the VPS. Adapted from green-harness deploy/release.sh.
# Run by GitHub Actions over SSH as the `studio` user, or by the owner by hand. The deploy key
# is authorised with a forced command (vps-bootstrap.sh): what the SSH client asks for arrives
# in SSH_ORIGINAL_COMMAND and only these verbs run:
#
#   release.sh deploy <image@sha256:digest> <ghcr-user>   stdin: a short-lived GHCR token
#   release.sh rollback                                    back to the previous digest
#   release.sh status                                      running, previous, health
#
# TRUST (as in the harness): this script, compose.yaml, the Caddyfile, probe.sh and .env are
# installed by vps-bootstrap.sh as root and are NOT writable by `studio`. CI sends one thing:
# an image digest. `studio` is in the docker group (root-equivalent), which is why it must
# never be able to change what `docker compose` runs; it writes state/ only.
#
# Exit codes: 0 healthy on the new image; 1 unhealthy and rolled back; 2 unhealthy and the
# rollback did not answer either, or a refusal.
set -euo pipefail

STUDIO_HOME="${STUDIO_HOME:-/srv/studio}"
STATE="$STUDIO_HOME/state"
DEFAULT_IMAGE_REPO="ghcr.io/greenflac/lipsync-templates"
# CHOSEN (as in the harness): 30 polls 4 s apart. A first start may issue the certificate.
HEALTH_TRIES=${HEALTH_TRIES:-30}
HEALTH_WAIT_S=4
TRUSTED=(release.sh probe.sh compose.yaml Caddyfile .env)

say() { echo "release: $*" >&2; }
refuse() { say "$*"; exit 2; }

trusted_files() {
  [ "$(id -u)" -eq 0 ] && return 0
  [ -w "$STUDIO_HOME" ] && refuse "$STUDIO_HOME is writable by $(id -un): refused"
  local dir child name
  child=$(cd "$STUDIO_HOME" && pwd -P)
  dir=$(dirname "$child")
  while :; do
    if [ -w "$dir" ] && { [ ! -k "$dir" ] || [ -O "$child" ]; }; then
      refuse "$dir is writable by $(id -un), so $child could be replaced: refused"
    fi
    [ "$dir" = / ] && break
    child=$dir
    dir=$(dirname "$dir")
  done
  for name in "${TRUSTED[@]}"; do
    [ -e "$STUDIO_HOME/$name" ] || continue
    if [ -w "$STUDIO_HOME/$name" ] || [ -L "$STUDIO_HOME/$name" ]; then
      refuse "$STUDIO_HOME/$name is writable by $(id -un) or a link: refused"
    fi
  done
}

compose() {
  docker compose --project-directory "$STUDIO_HOME" --file "$STUDIO_HOME/compose.yaml" \
    --env-file "$STUDIO_HOME/.env" --env-file "$STATE/release.env" "$@"
}

setting() {  # the value of NAME= in a KEY=VALUE file, quotes stripped
  local name=$1 file=$2
  [ -f "$file" ] || return 0
  sed -n "s/^${name}=//p" "$file" | tail -n 1 | tr -d "\"'"
}

domain() {
  local d
  d=$(setting STUDIO_DOMAIN "$STUDIO_HOME/.env")
  [ -n "$d" ] || refuse ".env has no STUDIO_DOMAIN"
  echo "$d"
}

probe_address() {
  # Where the public side listens: STUDIO_BIND_IP when set, else the loopback (the harness
  # owner's first release probed 127.0.0.1:443 while another service held it - b-292).
  local ip
  ip=$(setting STUDIO_BIND_IP "$STUDIO_HOME/.env")
  case "$ip" in
    "" | 0.0.0.0) echo 127.0.0.1 ;;
    *) [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || refuse ".env STUDIO_BIND_IP is not IPv4"
       echo "$ip" ;;
  esac
}

healthy() {
  # Two halves, both required:
  #  1. probe.sh over HTTPS through whichever Caddy serves the domain, resolved to this
  #     machine: /healthz 200, the OAuth metadata, and /mcp answering 401 with the challenge;
  #  2. the in-container probe (`http_app probe`): a one-minute token for the probe principal,
  #     initialize and tools/list through the OAuth front - a dead transport fails the release.
  local d i address
  d=$(domain)
  address=$(probe_address)
  for ((i = 1; i <= HEALTH_TRIES; i++)); do
    if sh "$STUDIO_HOME/probe.sh" "https://$d" --resolve "$d:443:$address" >/dev/null \
        && compose exec -T server python -m studio.mcp.http_app probe --port 8770 >/dev/null; then
      say "healthy: https://$d answered, and the MCP transport answered the probe (poll $i)"
      return 0
    fi
    sleep "$HEALTH_WAIT_S"
  done
  say "NOT healthy: https://$d did not answer in $HEALTH_TRIES polls"
  return 1
}

record() {  # file image
  printf 'STUDIO_IMAGE=%s\n' "$2" > "$STATE/.$1.new"
  mv "$STATE/.$1.new" "$STATE/$1"
}

switch_to() {
  record release.env "$1"
  compose up -d --remove-orphans
}

valid_image() { [[ $1 =~ ^${IMAGE_REPO}@sha256:[0-9a-f]{64}$ ]]; }
valid_user() { [[ $1 =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,37}[A-Za-z0-9])?$ ]]; }

deploy() {
  local image=$1 user=$2 running
  valid_image "$image" || refuse "refused image '$image': only $IMAGE_REPO@sha256:<digest>"
  valid_user "$user" || refuse "refused user '$user': not a GitHub login"
  running=$(setting STUDIO_IMAGE "$STATE/release.env")
  trap 'docker logout ghcr.io >/dev/null 2>&1' EXIT
  docker login ghcr.io --username="$user" --password-stdin >/dev/null
  docker pull --quiet "$image" >/dev/null
  docker logout ghcr.io >/dev/null 2>&1
  say "switching ${running:-<none>} -> $image"
  switch_to "$image"
  if healthy; then
    if [ -n "$running" ] && [ "$running" != "$image" ]; then
      record release.previous "$running"
    fi
    return 0
  fi
  if [ -z "$running" ] || [ "$running" = "$image" ]; then
    say "no other image to roll back to"
    exit 2
  fi
  say "rolling back to $running"
  switch_to "$running"
  if healthy; then exit 1; fi
  exit 2
}

rollback() {
  local previous current
  previous=$(setting STUDIO_IMAGE "$STATE/release.previous")
  current=$(setting STUDIO_IMAGE "$STATE/release.env")
  [ -n "$previous" ] || refuse "no previous image recorded in state/release.previous"
  [ "$previous" != "$current" ] || refuse "the previous image $previous is the running image"
  valid_image "$previous" || refuse "state/release.previous holds '$previous', not a digest"
  say "rolling back ${current:-<none>} -> $previous"
  switch_to "$previous"
  [ -n "$current" ] && record release.previous "$current"
  healthy || exit 2
}

status() {
  echo "running:  $(setting STUDIO_IMAGE "$STATE/release.env")"
  echo "previous: $(setting STUDIO_IMAGE "$STATE/release.previous")"
  compose ps
  HEALTH_TRIES=1 healthy
}

trusted_files
IMAGE_REPO=$(setting STUDIO_IMAGE_REPO "$STUDIO_HOME/.env")
IMAGE_REPO=${IMAGE_REPO:-$DEFAULT_IMAGE_REPO}
[[ $IMAGE_REPO =~ ^[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9._-]+)+$ ]] \
  || refuse ".env STUDIO_IMAGE_REPO '$IMAGE_REPO' is not a registry path"

# A forced command: the request is in SSH_ORIGINAL_COMMAND, split into words, never evaluated.
if [ -n "${SSH_ORIGINAL_COMMAND+x}" ]; then
  read -r -a request <<<"$SSH_ORIGINAL_COMMAND"
else
  request=("$@")
fi
verb="${request[0]:-}"
set -- "${request[@]:1}"

case "$verb:$#" in
  deploy:2) deploy "$1" "$2" ;;
  rollback:0) rollback ;;
  status:0) status ;;
  *) refuse "usage: release.sh deploy <image@sha256:digest> <ghcr-user> | rollback | status" ;;
esac
