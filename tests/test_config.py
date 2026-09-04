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


if __name__ == "__main__":
    unittest.main()
