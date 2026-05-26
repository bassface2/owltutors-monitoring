import json
import os


DETAILS_PATH = "details.json"


def write_detail(test_name: str, data: dict):
    """Merge per-test metadata into details.json (created if absent)."""
    existing = {}
    if os.path.exists(DETAILS_PATH):
        try:
            with open(DETAILS_PATH) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}
    existing[test_name] = data
    with open(DETAILS_PATH, "w") as f:
        json.dump(existing, f, indent=2)
