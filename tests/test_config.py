"""Tests for environment-based application configuration."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from my_openai_robot.config import AppConfig


class TestAppConfig(unittest.TestCase):
    def test_environment_overrides_dotenv_for_all_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "RETRY_MAX_RETRIES=2\nSTT_COST_PER_HOUR=1.5\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"RETRY_MAX_RETRIES": "7", "STT_COST_PER_HOUR": "2.5"},
                clear=True,
            ):
                config = AppConfig.from_env(env_file)

        self.assertEqual(config.retry.max_retries, 7)
        self.assertEqual(config.billing.stt_cost_per_hour, 2.5)


if __name__ == "__main__":
    unittest.main()