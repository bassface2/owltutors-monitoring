import json
import os
import sys
import requests


def post_results(report_path: str):
    with open(report_path) as f:
        report = json.load(f)

    results = {}
    for test in report.get("tests", []):
        name = test["nodeid"].split("::")[-1]
        outcome = test["outcome"]  # "passed", "failed", "error"
        call = test.get("call", {})
        results[name] = {
            "status":      "pass" if outcome == "passed" else "fail",
            "message":     str(call.get("longrepr", "OK"))[:300] if outcome != "passed" else "OK",
            "duration_ms": int(call.get("duration", 0) * 1000),
        }

    # Send as form-encoded POST — admin-ajax.php reads $_POST, not raw JSON body
    payload = {
        "action":  "owl_monitoring_results",
        "api_key": os.environ["OWL_TEST_API_KEY"],
        "results": json.dumps(results),
    }

    endpoint = os.environ["RESULTS_ENDPOINT"]
    r = requests.post(endpoint, data=payload, timeout=10)
    r.raise_for_status()

    data = r.json()
    if not data.get("success"):
        raise Exception(f"Endpoint error: {data.get('error', 'unknown')}")

    print(f"Posted {len(results)} results → {r.status_code}")


if __name__ == "__main__":
    post_results(sys.argv[1])
