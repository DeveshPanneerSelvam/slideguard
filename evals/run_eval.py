"""Evaluate SlideGuard on a held-out golden set.

The thresholds in slideguard/qc.py were tuned on development seeds. This eval
uses a different seed (99), half of the defects in a subtle "mild" form, and
labels set by how each image was made.

Gated metrics (CI fails if missed):
- false_pass_rate: defective slides that passed QC. This is the dangerous one:
  a bad image reaching an AI model. Must be 0.
- false_fail_rate: clean slides wrongly held back (wasted rescans). Max 5%.
- reason_accuracy: failed slides tagged with the right reason. Min 95%.

    python evals/run_eval.py
"""

import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from slideguard.qc import check_file, failure_codes  # noqa: E402
from slideguard.synth import write_set  # noqa: E402

SEED = 99
MIX = {"none": 40, "blur": 10, "low_tissue": 10, "pen_mark": 10, "faded": 10, "overstained": 10}
GATES = {"false_pass_rate": ("max", 0.0), "false_fail_rate": ("max", 0.05), "reason_accuracy": ("min", 0.95)}
RESULTS = ROOT / "evals" / "results.json"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        rows = write_set(Path(tmp), MIX, seed=SEED, prefix="GOLD", mild_share=0.5)
        outcomes = []
        for row in rows:
            result = check_file(row["path"])
            outcomes.append({**row, "passed": result.passed, "codes": sorted(failure_codes(result)),
                             "metrics": result.metrics})

    clean = [o for o in outcomes if o["defect"] == "none"]
    bad = [o for o in outcomes if o["defect"] != "none"]
    false_passes = [o for o in bad if o["passed"]]
    false_fails = [o for o in clean if not o["passed"]]
    right_reason = [o for o in bad if o["defect"] in o["codes"]]

    by_defect = defaultdict(lambda: {"total": 0, "caught": 0, "mild": 0, "mild_caught": 0})
    for o in bad:
        d = by_defect[o["defect"]]
        d["total"] += 1
        d["caught"] += o["defect"] in o["codes"]
        d["mild"] += o["mild"]
        d["mild_caught"] += o["mild"] and o["defect"] in o["codes"]

    report = {
        "seed": SEED,
        "slides": len(outcomes),
        "clean": len(clean),
        "defective": len(bad),
        "mild_defects": sum(o["mild"] for o in bad),
        "false_pass_rate": round(len(false_passes) / len(bad), 3),
        "false_fail_rate": round(len(false_fails) / len(clean), 3),
        "reason_accuracy": round(len(right_reason) / len(bad), 3),
        "by_defect": dict(by_defect),
        "false_passes": [{k: o[k] for k in ("slide_id", "defect", "mild", "metrics")} for o in false_passes],
        "false_fails": [{k: o[k] for k in ("slide_id", "codes", "metrics")} for o in false_fails],
    }
    RESULTS.write_text(json.dumps(report, indent=2) + "\n")

    print(f"Golden slides:     {report['slides']} ({report['clean']} clean, {report['defective']} defective, "
          f"{report['mild_defects']} of them mild)")
    print(f"False pass rate:   {report['false_pass_rate']:.1%}  (bad slide reached the model)")
    print(f"False fail rate:   {report['false_fail_rate']:.1%}  (clean slide held back)")
    print(f"Reason accuracy:   {report['reason_accuracy']:.1%}")
    for name, d in report["by_defect"].items():
        print(f"  {name:<12} caught {d['caught']}/{d['total']} (mild {d['mild_caught']}/{d['mild']})")

    failed = [k for k, (kind, limit) in GATES.items()
              if (report[k] > limit if kind == "max" else report[k] < limit)]
    if failed:
        print(f"FAILED gates: {failed}")
        return 1
    print("All eval gates met.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
