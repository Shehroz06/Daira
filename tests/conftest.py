"""Ensure project modules import cleanly regardless of pytest's rootdir.

Same sys.path idiom used by scripts/build_index.py and scripts/prepare_documents.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
