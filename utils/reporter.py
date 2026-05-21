import json
import os
import sys
from datetime import datetime, timezone


def write_results(report_path: str):
    with open(report_path) as f:
        report = json.load(f)

    results = {}
    for test in report.get("tests", []):
        name = test["nodeid"].split("::")[-1].split("[")[0]
        outcome = test["outcome"]  # "passed", "failed", "error"
        call = test.get("call", {})
        results[name] = {
            "status":      "pass" if outcome == "passed" else "fail",
            "message":     str(call.get("longrepr", "OK"))[:300] if outcome != "passed" else "OK",
            "duration_ms": int(call.get("duration", 0) * 1000),
        }

    output = {
        "last_run": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results":  results,
    }

    with open("results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(results)} results to results.json")


if __name__ == "__main__":
    write_results(sys.argv[1])
