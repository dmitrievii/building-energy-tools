from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

from epw_climate_analyzer.release_info import PUBLICATION_STATUS


TOOL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = REPO_ROOT / "deployment" / "streamlit-community-cloud.json"


class DeploymentContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_streamlit_community_cloud_coordinates_are_explicit(self) -> None:
        self.assertEqual(self.contract["stage"], "WEB-0.8")
        self.assertEqual(self.contract["target"], "Streamlit Community Cloud")
        self.assertEqual(self.contract["repository"], "dmitrievii/building-energy-tools")
        self.assertEqual(self.contract["branch"], "main")
        self.assertEqual(self.contract["entrypoint"], "tools/climate_analyzer/app.py")
        self.assertEqual(self.contract["python_version"], "3.12")
        self.assertTrue((REPO_ROOT / self.contract["entrypoint"]).is_file())
        self.assertTrue((REPO_ROOT / self.contract["dependency_file"]).is_file())

    def test_streamlit_config_exists_only_at_repository_root(self) -> None:
        root_config = REPO_ROOT / self.contract["streamlit_config"]
        old_tool_config = TOOL_ROOT / ".streamlit" / "config.toml"
        self.assertEqual(root_config, REPO_ROOT / ".streamlit" / "config.toml")
        self.assertTrue(root_config.is_file())
        self.assertFalse(old_tool_config.exists())

        config = tomllib.loads(root_config.read_text(encoding="utf-8"))
        self.assertTrue(config["server"]["headless"])
        self.assertEqual(config["server"]["maxUploadSize"], 10)
        self.assertEqual(config["server"]["maxMessageSize"], 50)
        self.assertFalse(config["browser"]["gatherUsageStats"])

    def test_public_release_remains_fail_closed(self) -> None:
        self.assertFalse(self.contract["public_release_allowed"])
        self.assertEqual(self.contract["current_publication_status"], PUBLICATION_STATUS)
        self.assertEqual(PUBLICATION_STATUS, "BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED")

    def test_subdomain_candidates_are_product_focused(self) -> None:
        candidates = self.contract["custom_subdomain_candidates"]
        self.assertGreaterEqual(len(candidates), 1)
        for candidate in candidates:
            self.assertRegex(candidate, r"^[a-z0-9-]{6,63}$")
            self.assertNotIn("dmitriev", candidate)
            self.assertIn("climate", candidate)


if __name__ == "__main__":
    unittest.main()
