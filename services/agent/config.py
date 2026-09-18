"""Agent service configuration. Pin real values once WP-01's checkpoint runs."""

from __future__ import annotations

import os

# Limits from SPEC section 9 / POA WP-04.
MAX_ITEMS_PER_SEARCH = 4
MAX_MERCHANTS = 2
SEARCH_CONCURRENCY = 2
ITEM_FETCH_DEADLINE_SECONDS = 45
MAX_REPAIR_ROUNDS = 2
MAX_MODEL_TURNS = 6
AGENT_DEADLINE_SECONDS = 90
WORKER_TIMEOUT_SECONDS = 100

TESTED_LOCALITY_PINCODE = os.environ.get("PROOFPATH_TEST_PINCODE", "110001")

BEDROCK_MODEL_ID = os.environ.get("PROOFPATH_BEDROCK_MODEL_ID", "")  # set after WP-01 checkpoint
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

# Server-only token validated on every task request; rotated by P4's infra.
AGENT_SERVICE_TOKEN = os.environ.get("PROOFPATH_AGENT_TOKEN", "")
