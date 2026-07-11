"""Import size/row limits, centralized and env-configurable with
conservative defaults — same pattern as app/ai/limits.py. Entity-agnostic;
every future import (Products, Invoices, ...) reuses these same knobs
unless a specific entity genuinely needs its own.
"""

import os

IMPORT_MAX_FILE_SIZE_BYTES = int(os.environ.get("IMPORT_MAX_FILE_SIZE_BYTES", str(5_000_000)))
IMPORT_MAX_ROWS = int(os.environ.get("IMPORT_MAX_ROWS", "2000"))
# Rows actually returned to the frontend for display in the preview step —
# independent of IMPORT_MAX_ROWS, which bounds what's accepted/validated
# server-side. Keeps a 2000-row file from producing an unnecessarily huge
# preview response while every row is still fully validated.
IMPORT_MAX_PREVIEW_ROWS = int(os.environ.get("IMPORT_MAX_PREVIEW_ROWS", "50"))
