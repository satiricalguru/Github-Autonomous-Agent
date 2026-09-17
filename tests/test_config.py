import sys
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import AgentConfig



class TestConfig(unittest.TestCase):
    def test_default_config(self):
        cfg = AgentConfig()
        self.assertTrue(isinstance(cfg.target_languages, list))
        self.assertIn("python", cfg.target_languages)
        self.assertGreater(cfg.min_repo_stars, 0)
        self.assertTrue(isinstance(cfg.scratch_dir, Path))
        self.assertTrue(cfg.scratch_dir.exists())

    def test_repo_filtering_config(self):
        cfg = AgentConfig()
        self.assertTrue(isinstance(cfg.allowed_repos, list))
        self.assertTrue(isinstance(cfg.denied_repos, list))
        self.assertIn("GTNewHorizons/GT-New-Horizons-Modpack", cfg.denied_repos)
        self.assertGreater(cfg.max_repo_size_kb, 1000)
        self.assertIn("allowed_repos", cfg.public_settings())
        self.assertIn("denied_repos", cfg.public_settings())
        self.assertIn("max_repo_size_kb", cfg.public_settings())


if __name__ == "__main__":
    unittest.main()
