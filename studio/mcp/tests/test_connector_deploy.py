"""The deploy files agree with the app and with each other (green-harness test_deploy_files).

Nothing here starts a container or reaches a network: the files are read as text.
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest import mock

from studio.mcp import http_app
from studio.mcp.connector_store import ConnectorStore

ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / "deploy"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-connector.yml"


def caddy_paths(text: str) -> set[str]:
    line = next(x for x in text.splitlines() if x.strip().startswith("@app path "))
    return set(line.split()[2:])


class CaddyPassesExactlyTheAppsPaths(unittest.TestCase):
    def setUp(self) -> None:
        with mock.patch.dict(os.environ, {"STUDIO_MCP_WARM_INDEX": "0"}):
            app = http_app.build_app(ConnectorStore(":memory:"), domain="studio.example.org")
        self.paths = {route.path for route in app.inner.router.routes}

    def test_every_route_is_proxied_and_nothing_else(self) -> None:
        wanted = self.paths | {"/mcp/*"}
        for name in ("Caddyfile", "Caddyfile.harness-site"):
            with self.subTest(name):
                self.assertEqual(caddy_paths((DEPLOY / name).read_text()), wanted)


class SecretsAreFiles(unittest.TestCase):
    def test_compose_names_secret_files_and_no_secret_values(self) -> None:
        text = (DEPLOY / "compose.yaml").read_text()
        self.assertIn("STUDIO_KEY_PEPPER_FILE: /run/secrets/key_pepper", text)
        self.assertIn("STUDIO_VENDOR_ENV_FILE: /run/secrets/vendor_env", text)
        self.assertNotRegex(text, r"(?m)^\s+STUDIO_KEY_PEPPER:")
        self.assertNotRegex(text, r"(?i)(api_key|token|password)\s*[:=]\s*\S{8,}")


class OneImageName(unittest.TestCase):
    def test_workflow_release_and_env_name_the_same_repository(self) -> None:
        image = re.search(r"(?m)^\s+IMAGE: (\S+)$", WORKFLOW.read_text()).group(1)  # type: ignore[union-attr]
        release = re.search(r'DEFAULT_IMAGE_REPO="([^"]+)"', (DEPLOY / "release.sh").read_text())
        env = re.search(r"(?m)^STUDIO_IMAGE_REPO=(\S+)$", (DEPLOY / ".env.example").read_text())
        self.assertEqual({image, release.group(1), env.group(1)}, {image})  # type: ignore[union-attr]


class Pinned(unittest.TestCase):
    def test_every_action_is_pinned_by_a_full_sha(self) -> None:
        uses = re.findall(r"uses: (\S+)", WORKFLOW.read_text())
        self.assertTrue(uses)
        for ref in uses:
            self.assertRegex(ref, r"@[0-9a-f]{40}$", ref)

    def test_base_images_are_pinned_by_digest(self) -> None:
        for name in ("Dockerfile", "compose.yaml"):
            for line in (DEPLOY / name).read_text().splitlines():
                if re.match(r"\s*(FROM|image:)\s", line) and "${" not in line:
                    self.assertRegex(line, r"@sha256:[0-9a-f]{64}", line)

    def test_the_dockerfile_reads_seven_runtime_pins_that_exist(self) -> None:
        pattern = re.search(r"grep -E '(\^\([^']+\)==)'", (DEPLOY / "Dockerfile").read_text())
        assert pattern
        regex = re.compile(pattern.group(1))
        pins = [
            line
            for line in (ROOT / "requirements-dev.txt").read_text().splitlines()
            if regex.match(line)
        ]
        self.assertEqual(len(pins), 7, pins)


if __name__ == "__main__":
    unittest.main()
