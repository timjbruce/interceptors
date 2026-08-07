"""Shared configuration, read from the environment.

Local by default; set the TEMPORAL_* vars (see setcloudenv.example) to point the
worker, web client, and CLI at Temporal Cloud instead.
"""

import os

TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "interceptor-samples")
TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")

# The JWT-authorized backend service the activities call over HTTP.
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:9000")

# Encrypt all payloads + headers on the wire and in Event History when set.
ENCRYPT_PAYLOADS = os.getenv("ENCRYPT_PAYLOADS", "").lower() == "true"
