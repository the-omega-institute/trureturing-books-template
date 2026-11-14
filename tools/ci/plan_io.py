"""Read complete CI plans from a same-run artifact without oversized environment values."""
import json
import os
from pathlib import Path


def load_plan():
    # Retain the explicit local/test interface; managed workflows use the plan file.
    if "PLAN_JSON" in os.environ:
        return json.loads(os.environ["PLAN_JSON"])
    return json.loads(Path(os.environ.get("PLAN_FILE", "ci-plan.json")).read_text())


def workflow_controls(plan):
    """Only conditions cross job outputs; execution and coverage keep the complete file."""
    return {
        "profiles": plan["profiles"],
        "selections": {profile: {"checks": selected["checks"]}
                       for profile, selected in plan["selections"].items()},
        "coverage": {profile: True for profile in plan["coverage"]},
    }
