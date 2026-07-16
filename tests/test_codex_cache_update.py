from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
SCRIPT = PROJECT_ROOT / "skills" / "codex-cache-update" / "scripts" / "update.sh"


class TestCodexCacheUpdate(unittest.TestCase):
    def test_syncs_versioned_cache_and_deletes_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            marketplace = root / "marketplace"
            cache_root = root / "cache"
            marketplace_manifest = marketplace / ".codex-plugin" / "plugin.json"
            marketplace_manifest.parent.mkdir(parents=True)
            marketplace_manifest.write_text(json.dumps({"version": "0.3.43"}))
            source_skill = marketplace / "skills" / "example" / "SKILL.md"
            source_skill.parent.mkdir(parents=True)
            source_skill.write_text("latest\n")

            cache = cache_root / "0.3.43"
            cache.mkdir(parents=True)
            (cache / "stale.txt").write_text("remove\n")

            fake_bin = root / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text("#!/bin/sh\nexit 0\n")
            codex.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "CODEX_MARKETPLACE_DIR": str(marketplace),
                "CODEX_CACHE_ROOT": str(cache_root),
            }

            result = subprocess.run(
                ["bash", str(SCRIPT)],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((cache / "skills" / "example" / "SKILL.md").read_text(), "latest\n")
            self.assertFalse((cache / "stale.txt").exists())
            self.assertIn("cache synchronized", result.stdout)


if __name__ == "__main__":
    unittest.main()
