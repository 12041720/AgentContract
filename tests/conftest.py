"""Global pytest fixtures and test configuration."""

import os

# Prevent local repository .env from polluting offline unit test environments
os.environ["AGENTCONTRACT_DISABLE_ENV_FILE"] = "1"
