"""Command line for the lab team.

    python -m slideguard.cli generate              # make synthetic demo slides
    python -m slideguard.cli check data/slides     # run QC on a folder of images
    python -m slideguard.cli failed                # slides held back, with reasons
    python -m slideguard.cli draft SLIDE-004       # draft a rescan request
    python -m slideguard.cli pending               # requests waiting for a person
    python -m slideguard.cli approve 1 --reviewer "Your Name"
    python -m slideguard.cli reject 1 --reviewer "Your Name"
    python -m slideguard.cli metrics

Approve/reject live here, not in the MCP server: an agent drafts, a person decides.
"""

import argparse
import json
import os
from pathlib import Path

from slideguard import service, store
from slideguard.synth import write_set

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("SLIDEGUARD_DB", ROOT / "slideguard.db"))
DEMO_DIR = ROOT / "data" / "slides"
DEMO_MIX = {"none": 30, "blur": 4, "low_tissue": 3, "pen_mark": 3, "faded": 2, "overstained": 2}


def main() -> None:
    parser = argparse.ArgumentParser(prog="slideguard")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate")
    c = sub.add_parser("check")
    c.add_argument("folder", nargs="?", default=str(DEMO_DIR))
    f = sub.add_parser("failed")
    f.add_argument("--reason")
    d = sub.add_parser("draft")
    d.add_argument("slide_id")
    sub.add_parser("pending")
    for name in ("approve", "reject"):
        r = sub.add_parser(name)
        r.add_argument("request_id", type=int)
        r.add_argument("--reviewer", required=True)
        if name == "approve":
            r.add_argument("--edited-body-file")
    sub.add_parser("metrics")
    args = parser.parse_args()

    if args.cmd == "generate":
        rows = write_set(DEMO_DIR, DEMO_MIX, seed=3, prefix="SLIDE", mild_share=0.3)
        print(json.dumps({"generated": len(rows), "folder": str(DEMO_DIR)}, indent=2))
        return

    conn = store.connect(DB_PATH)
    if args.cmd == "check":
        out = service.run_qc(conn, args.folder, actor="cli")
    elif args.cmd == "failed":
        out = service.failed_slides(conn, args.reason)
    elif args.cmd == "draft":
        out = service.draft_rescan(conn, args.slide_id, actor="cli")
    elif args.cmd == "pending":
        out = store.requests(conn, "pending_approval")
    elif args.cmd in ("approve", "reject"):
        body = Path(args.edited_body_file).read_text().strip() if getattr(args, "edited_body_file", None) else None
        try:
            out = store.review_request(conn, args.request_id, args.reviewer, args.cmd == "approve", body)
        except ValueError as exc:
            out = {"error": str(exc)}
    else:
        out = service.metrics(conn)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
