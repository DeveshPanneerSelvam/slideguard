"""Actions shared by the CLI and the MCP server, so guardrails apply to both."""

import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

from slideguard import store
from slideguard.qc import THRESHOLDS, check_file

MAX_RESULTS = 50

# What a lab lead would usually try for each failure. Suggestions only:
# a person decides what actually happens to the slide.
SUGGESTED_ACTION = {
    "blur": "Rescan with refocusing (check focus points and slide seating).",
    "low_tissue": "Check that the scan area covers the tissue; rescan, or review the section if tissue is genuinely sparse.",
    "pen_mark": "Clean marker ink off the coverslip and rescan.",
    "faded": "Review staining quality; rescan or restain per lab procedure.",
    "overstained": "Review staining quality; rescan or restain per lab procedure.",
    "unreadable": "Re-export or re-upload the image file.",
}

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")
log = logging.getLogger("slideguard")


def _trace(action: str, started: float, **fields) -> None:
    log.info(json.dumps({"event": "action", "action": action,
                         "ms": round((time.perf_counter() - started) * 1000, 1), **fields}, default=str))


def run_qc(conn, folder: str | Path, actor: str = "qc") -> dict:
    started = time.perf_counter()
    paths = sorted(Path(folder).glob("*.png")) + sorted(Path(folder).glob("*.jpg"))
    failed = 0
    for path in paths:
        result = check_file(str(path))
        store.save_result(conn, path.stem, str(path), result, actor)
        failed += not result.passed
    _trace("run_qc", started, checked=len(paths), failed=failed)
    return {"checked": len(paths), "passed": len(paths) - failed, "failed": failed}


def failed_slides(conn, reason: str | None = None, limit: int = 20) -> dict:
    rows = store.slides(conn, passed=False)
    if reason:
        rows = [r for r in rows if any(f.startswith(reason) for f in r["failures"])]
    limit = max(1, min(limit, MAX_RESULTS))
    return {"count": len(rows), "slides": [
        {"slide_id": r["slide_id"], "failures": r["failures"]} for r in rows[:limit]
    ]}


def slide_detail(conn, slide_id: str) -> dict:
    s = store.slide(conn, slide_id)
    if not s:
        return {"error": f"Slide {slide_id} not found"}
    s["thresholds"] = THRESHOLDS
    s["requests"] = [{k: r[k] for k in ("id", "status")}
                     for r in store.requests(conn) if r["slide_id"] == slide_id]
    return s


def draft_rescan(conn, slide_id: str, actor: str = "agent") -> dict:
    s = store.slide(conn, slide_id)
    if not s:
        return {"error": f"Slide {slide_id} not found"}
    if s["passed"]:
        return {"error": f"Slide {slide_id} passed QC; no rescan needed"}
    if any(r["slide_id"] == slide_id for r in store.requests(conn, "pending_approval")):
        return {"error": f"Slide {slide_id} already has a rescan request waiting for review"}
    codes = [f.split(":")[0] for f in s["failures"]]
    lines = [f"Rescan request: slide {slide_id}", "", "Failed image quality checks:"]
    lines += [f"- {f}" for f in s["failures"]]
    lines += ["", "Suggested next steps (lab lead to decide):"]
    lines += [f"- {SUGGESTED_ACTION.get(c, 'Review manually.')}" for c in dict.fromkeys(codes)]
    lines += ["", "This slide has been held back from automated analysis until it passes QC."]
    body = "\n".join(lines)
    request_id = store.save_request(conn, slide_id, body, actor)
    return {"request_id": request_id, "status": "pending_approval", "body": body,
            "note": "Not sent. A named person must approve it."}


def metrics(conn) -> dict:
    rows = store.slides(conn)
    failed = [r for r in rows if not r["passed"]]
    reasons = Counter(f.split(":")[0] for r in failed for f in r["failures"])
    reviewed = [r for r in store.requests(conn) if r["status"] != "pending_approval"]
    return {
        "slides_checked": len(rows),
        "qc_fail_rate": round(len(failed) / len(rows), 3) if rows else None,
        "failures_by_reason": dict(reasons.most_common()),
        "rescan_requests_pending": len(store.requests(conn, "pending_approval")),
        "request_approval_rate": (round(sum(r["status"] == "approved" for r in reviewed) / len(reviewed), 2)
                                  if reviewed else None),
        "request_human_edit_rate": (round(sum(r["edited"] for r in reviewed) / len(reviewed), 2)
                                    if reviewed else None),
    }
