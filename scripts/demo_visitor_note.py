"""Run the visitor-note demonstration.

    python scripts/demo_visitor_note.py          # offline mock (no API credits)
    python scripts/demo_visitor_note.py --live   # uses your stored API key
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kimi.demo import run_demo  # noqa: E402

if __name__ == "__main__":
    sys.exit(run_demo(live="--live" in sys.argv))
