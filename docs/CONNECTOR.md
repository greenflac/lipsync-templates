# The studio as a claude.ai connector

`lipsync-studio` (the MCP server in `studio/mcp/server.py`) can run as a **claude.ai custom
connector**: remote MCP over HTTPS at `https://studio.greenflac.online/mcp`, signed in with
OAuth. It is built exactly like the green-harness connector at
`https://harness.greenflac.online/mcp`, and from its code.

**Why.** In a cloud session the project stdio server (`.mcp.json`) starts on the session's
cold container. It timed out on connect, and the app could not reconnect it. A connector is
reached through Anthropic's servers and runs warm on our machine. Each person adds it once in
claude.ai, and every session has it after that: web, desktop and Claude Code cloud sessions.

## What runs

| piece | file |
|---|---|
| HTTP app: streamable HTTP `/mcp` (stateless, JSON), OAuth routes, sign-in page, `/healthz` | `studio/mcp/http_app.py` |
| OAuth provider: dynamic client registration, PKCE S256, rotating refresh tokens, replay ends the family | `studio/mcp/oauth.py` |
| Store: users, OAuth clients and grants (hashed under a pepper), attribution rows | `studio/mcp/connector_store.py` |
| Cheap start: planner, endpoints, recipes, factindex and capability import on first use | `studio/mcp/lazy.py` (+ 2 import lines in `server.py`, 1 in `screen.py`) |
| Image, compose (no Caddy), harness site block, release, probe, bootstrap | `deploy/` |
| Release pipeline | `.github/workflows/deploy-connector.yml` |
| Tests | `studio/mcp/tests/test_connector_http.py`, `test_connector_deploy.py`, `scripts/connector_smoke.py` |

**Identity.** Every person has a **studio user**: a name (`owner`, `anna`) and a random key.
The owner issues it on the VPS. At sign-in the person types the key on our own page, once. From
then on the connector holds its own tokens: access tokens last 1 h, refresh tokens last 30 days
and are rotated. The raw key is never a bearer at `/mcp`.

**Attribution.** Five tools spend money or write the shared base:
- `record_model_fact`
- `withdraw_model_fact`
- `propose_measurement`
- `search_web`, which uses the owner's search key
- `probe_model_limit`, which uses a vendor key

They run only for a signed-in user. Each call leaves a row before the tool runs, with the time,
the user, the OAuth client, the tool and its arguments. To read the rows:

```sh
sc exec server python -m studio.mcp.http_app calls --limit 50 [--user anna]
```

Without OAuth (`STUDIO_DOMAIN` unset, loopback dev mode) these tools are refused.

## Where it runs: the green-harness VPS (owner decision 2026-10-19)

The studio shares only the harness's **Caddy**. Everything else is its own:

| | harness | studio |
|---|---|---|
| compose project | `/srv/harness` | `/srv/studio` (`deploy/compose.yaml`, no Caddy) |
| deploy user and key | `harness`, forced command `/srv/harness/release.sh` | `studio`, forced command `/srv/studio/release.sh` |
| secrets | `/srv/harness/secrets` | `/srv/studio/secrets` (`key_pepper`, `vendor.env`) |
| public side | Caddy on 80/443 | the same Caddy: the `studio.greenflac.online` site block |

**How Caddy reaches the studio server.** The harness compose (green_harness `deploy/`, from
REVISION 10) creates the internal network `harness-studio-edge` (172.31.251.0/24) and puts
its Caddy there at the fixed address 172.31.251.2. The studio compose joins that network as
`external`, with the alias `studio-server`. Caddy proxies `studio.greenflac.online` to
`studio-server:8770`. The studio trusts `X-Forwarded-For` only from 172.31.251.2. The server
is also published on `127.0.0.1:8770`, for checks on the VPS. It has its own network for the
way out (fetch, search), because `harness-studio-edge` is internal.

The site block lives in two places, byte for byte the same:
- `deploy/Caddyfile.harness-site` here; the tests keep its path list equal to the app's routes.
- `deploy/Caddyfile` in green_harness: local branch `studio-connector-site`, commit `ae9a9fa`,
  based on `claude/pensive-cerf-coznsv`. That is the branch the harness releases from: its
  `deploy.yml` and guard allow v* tags on `main` or on that branch, and `main` has no
  `deploy/`. The commit is not pushed.

**SSH.** The harness key's forced command is **not** extended. The studio gets its own user and
its own key. `vps-bootstrap.sh` appends this one line to `/home/studio/.ssh/authorized_keys`
(the key is generated there):

```
restrict,command="/srv/studio/release.sh" ssh-ed25519 AAAA...<generated> studio-deploy
```

`/home/harness/.ssh/authorized_keys` is left as it is. The lipsync repository's environment
`connector` uses the same five secret names. `VPS_HOST`, `VPS_PORT` and `VPS_KNOWN_HOSTS` have
the harness's values (same machine, same host key). `VPS_USER` is `studio`, and `VPS_SSH_KEY`
is the new key.

## Owner steps on the shared VPS (exactly, in order)

1. **DNS.** At the DNS provider of `greenflac.online`, add an **A record**:
   `studio` → the same IPv4 as `harness.greenflac.online`. Do this first, because the harness
   Caddy asks for the certificate as soon as it has the site block.
2. **Harness side.** In `green_harness`:
   1. Review branch `studio-connector-site` (commit `ae9a9fa`: Caddyfile site block, Caddy on
      `harness-studio-edge`, REVISION 10, RUNBOOK section 14).
   2. Merge it into `claude/pensive-cerf-coznsv` and push.
   3. On the VPS, install that `deploy/` as for any harness configuration change (harness
      RUNBOOK section 4):
      ```sh
      scp -r deploy/ you@VPS:harness-deploy/
      sudo HARNESS_DOMAIN=harness.greenflac.online ACME_EMAIL=... VPS_PUBLIC_HOST=... \
           bash harness-deploy/vps-bootstrap.sh
      hc up -d
      ```
      Caddy is recreated. `harness.greenflac.online` keeps working, and `studio.` answers 502
      until step 7.
3. **Studio bootstrap** on the VPS, once:
   ```sh
   scp -r deploy/ you@VPS:studio-deploy/
   sudo VPS_PUBLIC_HOST=<the harness's VPS_HOST> bash studio-deploy/vps-bootstrap.sh
   ```
   It refuses to run until `harness-studio-edge` exists (step 2). It copies the harness's
   `HARNESS_BIND_IP` into `STUDIO_PROBE_IP`, and it prints the new private key once.
4. **GitHub.** In `greenflac/lipsync-templates`, go to Settings → Environments → New
   environment `connector`:
   - Required reviewers: yourself.
   - Deployment branches and tags: Selected → tag rule `connector-v*`.
   - Secrets: `VPS_HOST`, `VPS_PORT` and `VPS_KNOWN_HOSTS` with the harness values;
     `VPS_USER`=`studio`; `VPS_SSH_KEY`=the printed key.
   - Variable: `STUDIO_DOMAIN`=`studio.greenflac.online`.
5. **Vendor keys (optional).** As root, put `NAME=value` lines (`GEMINI_API_KEY=...`) in
   `/srv/studio/secrets/vendor.env`. The file is mode 600 and owned by uid 10002.
6. **Release.** Tag a commit on `main` and push the tag, then approve the deploy in Actions:
   ```sh
   git tag connector-v0.1.0 && git push origin connector-v0.1.0
   ```
   The workflow runs in this order:
   1. guard
   2. `studio/mcp` tests and the loopback smoke test
   3. image build and push to GHCR (`ghcr.io/greenflac/lipsync-templates`)
   4. SSH deploy of the digest to `release.sh`
   5. checks on the VPS: `probe.sh` over HTTPS through the harness Caddy, plus the in-container
      MCP probe
   6. a check from outside, with a rollback if any of these fail
7. **Your user.** On the VPS, define the alias and create the user. The key is printed once.
   ```sh
   alias sc='sudo docker compose --project-directory /srv/studio -f /srv/studio/compose.yaml --env-file /srv/studio/.env --env-file /srv/studio/state/release.env'
   sc exec server python -m studio.mcp.http_app new-user owner
   ```
   Make one user per person.
8. **claude.ai:**
   1. Go to Settings → Connectors → Add custom connector.
   2. Name it `lipsync-studio` and set the URL to `https://studio.greenflac.online/mcp`.
   3. Click Connect and type the studio key on the sign-in page.
9. **Retire** `lipsync-studio` from `.mcp.json` for cloud sessions once the connector works.

## The knowledge base on the server (owner decision, open)

The connector writes facts, proposals and journals to the `knowledge` docker volume. On the
first start that volume is seeded from `studio/knowledge/` in the image. After that it is the
live base: a later release does **not** overwrite it, and what users record there does not
reach git by itself. The `calls` rows say who wrote what. **Undecided:** how the server's base
and the repository's base are merged, and in which direction. One option is a periodic export
of new rows into a PR.

The private prompt corpus (`corpus/`, gitignored) is not in the image either. The index uses
what `studio/knowledge` and `studio/selfrag/fixtures` carry, unless the corpus is copied onto a
volume and `STUDIO_CORPUS_PATHS` points there. The dense channel is off (`STUDIO_MCP_DENSE=0`):
the image carries no sentence-transformers.

## Local checks

```sh
python scripts/run_tests.py studio/mcp/tests          # includes the connector suites
python scripts/connector_smoke.py                     # real HTTP on 127.0.0.1, full OAuth walk
python -m studio.mcp.http_app serve --port 8770       # loopback, no OAuth, guarded tools refused
```

## What is not verified

- No live deploy has been made. The image has not been built in CI yet, and the DNS record
  does not exist yet.
- The proxy path over `harness-studio-edge` and Caddy's peer address there
  (`STUDIO_TRUSTED_PROXIES`) are not yet measured on the live VPS. The harness change is
  committed locally only; its suite was not run here (no pytest in this container).
- `mcp` here is 2.1.1. The harness runs 2.2, where `RefreshToken` also carries `resource`. The
  provider stores the resource in the grant so that it works on both versions.
