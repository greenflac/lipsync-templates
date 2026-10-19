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
| Image, compose, Caddy, release, probe, bootstrap | `deploy/` |
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

## Where it runs (owner decision)

The harness VPS already runs the harness Caddy on 80/443, and on that machine an Xray VPN
also uses `127.0.0.1:443` (harness b-292). A second Caddy cannot bind there. Two layouts are
prepared, and `vps-bootstrap.sh` picks one with `STUDIO_LAYOUT`:

- **`harness`: the same VPS (no new machine).** The studio compose publishes the server on
  `127.0.0.1:8770` only. Add `deploy/Caddyfile.harness-site` to the **harness** Caddyfile, and
  `extra_hosts: ["host.docker.internal:host-gateway"]` to the harness compose's `caddy`
  service. Both are changes in the `green_harness` repository. Ship them through its own
  reviewed `deploy/` and bootstrap rerun (harness RUNBOOK section 4), and raise its `REVISION`.
- **`own`: a VPS of its own.** This compose also runs Caddy (`COMPOSE_PROFILES=tls`). It gets
  the certificate itself, as the harness does. You need Ubuntu 22.04+ or Debian 12, 1 vCPU,
  2 GB RAM and Docker. Harden SSH, ufw and fail2ban first, as in harness RUNBOOK section 2.

## Owner steps (exactly)

1. **DNS.** At the DNS provider of `greenflac.online`, add an **A record**:
   `studio` → the public IPv4 of the chosen VPS. With the `harness` layout, that is the same
   IP that `harness.greenflac.online` points to.
2. **GitHub environment.** In `greenflac/lipsync-templates`, go to Settings → Environments →
   New environment `connector`:
   - Required reviewers: yourself.
   - Deployment branches and tags: Selected → tag rule `connector-v*`.
   - Environment variable `STUDIO_DOMAIN` = `studio.greenflac.online`.
3. **VPS bootstrap**, once, as your sudo user on the VPS:
   ```sh
   scp -r deploy/ you@VPS:studio-deploy/
   ssh you@VPS
   sudo STUDIO_DOMAIN=studio.greenflac.online VPS_PUBLIC_HOST=<VPS IPv4> \
        STUDIO_LAYOUT=harness ACME_EMAIL=<you@...> bash studio-deploy/vps-bootstrap.sh
   ```
   It prints five values. Add them to the `connector` environment as **secrets**:
   - `VPS_HOST`
   - `VPS_PORT`
   - `VPS_USER`
   - `VPS_SSH_KEY`, which is shown once
   - `VPS_KNOWN_HOSTS`

   The deploy key can run only `release.sh`, because it is a forced command.
4. **With the `harness` layout:** add the studio site block to the harness Caddy, as
   described in "Where it runs".
5. **Vendor keys (optional).** `search_web` and `probe_model_limit` use the owner's keys. As
   root on the VPS, put `NAME=value` lines (`GEMINI_API_KEY=...`, `SERPER_API_KEY=...`) in
   `/srv/studio/secrets/vendor.env`. That file is mode 600 and owned by uid 10002. The server
   loads it into its own process at start, so the keys are not in `docker inspect`. Without
   keys the tools still work and say "no key".
6. **Release:** tag a commit on `main` and push the tag.
   ```sh
   git tag connector-v0.1.0 && git push origin connector-v0.1.0
   ```
   Then approve the deploy in Actions. The workflow runs in this order:
   1. guard
   2. `studio/mcp` tests and the loopback smoke test
   3. image build and push to `ghcr.io/greenflac/lipsync-templates`
   4. SSH deploy of the digest
   5. health checks: `probe.sh` over HTTPS, plus the in-container MCP probe through the OAuth
      front
   6. a check from outside, with a rollback if any of these fail
7. **Create your user** on the VPS. The key is printed once; keep it in your password manager.
   ```sh
   alias sc='sudo docker compose --project-directory /srv/studio -f /srv/studio/compose.yaml --env-file /srv/studio/.env --env-file /srv/studio/state/release.env'
   sc exec server python -m studio.mcp.http_app new-user owner
   ```
   Make one user per person. `rekey-user NAME` replaces a key and ends that person's
   sign-ins. `disable-user NAME` locks a person out.
8. **Add the connector in claude.ai:**
   1. Go to Settings → Connectors → Add custom connector.
   2. Name it `lipsync-studio` and set the URL to `https://studio.greenflac.online/mcp`.
   3. Click Connect. claude.ai registers itself and opens our sign-in page.
   4. Type the studio key there. You are sent back to claude.ai, connected.

   Enable it in a session from the tools menu. Claude Code cloud sessions see claude.ai
   connectors too.
9. **Retire the stdio entry** for cloud sessions once the connector works. Remove
   `lipsync-studio` from `.mcp.json`, or keep it only for local runs. Two servers with the
   same tools would split the calls.

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
- The `harness` layout's proxy path (`host.docker.internal` → the loopback publish) and the
  peer address it arrives from (`STUDIO_TRUSTED_PROXIES`) are unmeasured on the live VPS.
- `mcp` here is 2.1.1. The harness runs 2.2, where `RefreshToken` also carries `resource`. The
  provider stores the resource in the grant so that it works on both versions.
