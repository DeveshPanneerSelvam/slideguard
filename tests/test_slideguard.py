import cv2
import numpy as np
import pytest

from slideguard import service, store
from slideguard.qc import check, check_file, failure_codes
from slideguard.synth import DEFECTS, make_tile, write_set


@pytest.mark.parametrize("defect", DEFECTS[1:])
@pytest.mark.parametrize("mild", [False, True])
def test_each_defect_is_caught_with_the_right_reason(defect, mild) -> None:
    result = check(make_tile(defect, seed=4242, mild=mild))
    assert not result.passed
    assert defect in failure_codes(result)


def test_clean_slide_passes_and_reports_metrics() -> None:
    result = check(make_tile("none", seed=4242))
    assert result.passed
    assert set(result.metrics) == {"tissue_fraction", "sharpness", "pen_fraction",
                                   "stain_saturation", "stain_brightness"}


def test_every_failure_explains_itself() -> None:
    result = check(make_tile("blur", seed=1))
    assert any("sharpness" in f and "needs" in f for f in result.failures)


def test_blank_image_fails_as_low_tissue() -> None:
    blank = np.full((384, 384, 3), 245, np.uint8)
    assert failure_codes(check(blank)) == {"low_tissue"}


def test_unreadable_file_fails_safely(tmp_path) -> None:
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not an image")
    result = check_file(str(bad))
    assert not result.passed and result.failures[0].startswith("unreadable")


@pytest.fixture
def conn(tmp_path):
    write_set(tmp_path / "slides", {"none": 3, "blur": 2, "pen_mark": 1}, seed=5, prefix="T")
    connection = store.connect(tmp_path / "test.db")
    service.run_qc(connection, tmp_path / "slides")
    yield connection
    connection.close()


def test_run_qc_and_metrics(conn) -> None:
    m = service.metrics(conn)
    assert m["slides_checked"] == 6
    assert m["failures_by_reason"] == {"blur": 2, "pen_mark": 1}


def test_draft_only_for_failed_slides_and_no_duplicates(conn) -> None:
    failed_id = service.failed_slides(conn)["slides"][0]["slide_id"]
    passed_id = store.slides(conn, passed=True)[0]["slide_id"]
    assert "error" in service.draft_rescan(conn, passed_id)
    first = service.draft_rescan(conn, failed_id)
    assert first["status"] == "pending_approval"
    assert "held back from automated analysis" in first["body"]
    assert "error" in service.draft_rescan(conn, failed_id)


def test_approval_needs_named_reviewer_once_and_is_audited(conn) -> None:
    failed_id = service.failed_slides(conn)["slides"][0]["slide_id"]
    request_id = service.draft_rescan(conn, failed_id, actor="mcp-agent")["request_id"]
    with pytest.raises(ValueError):
        store.review_request(conn, request_id, " ", approve=True)
    assert store.review_request(conn, request_id, "Lab Lead", approve=True, new_body="edited")["edited"]
    with pytest.raises(ValueError):
        store.review_request(conn, request_id, "Lab Lead", approve=True)
    actions = [r["action"] for r in conn.execute(
        "SELECT action FROM events WHERE request_id = ? ORDER BY id", (request_id,))]
    assert actions == ["rescan_drafted", "approved"]
    assert service.metrics(conn)["request_human_edit_rate"] == 1.0


def test_results_are_capped(conn) -> None:
    assert len(service.failed_slides(conn, limit=10_000)["slides"]) <= service.MAX_RESULTS


def test_written_tiles_are_valid_images(tmp_path) -> None:
    rows = write_set(tmp_path, {"none": 1}, seed=1, prefix="X")
    assert cv2.imread(rows[0]["path"]).shape == (384, 384, 3)
