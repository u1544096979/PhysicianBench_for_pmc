from pathlib import Path

from scripts.generate_all_oncology_tasks import generate_all_cases


class FakeClient:
    def chat(self, messages):
        raise RuntimeError("fake generation failure")


def test_batch_isolates_failures_and_writes_review_queue(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    raw.mkdir(parents=True)
    (raw / "case-1.csv").write_text("case_id\ncase-1\n")
    summary = generate_all_cases(tmp_path, tmp_path / "tasks", client=FakeClient())
    assert summary.processed == 1
    assert summary.rejected == 1
    assert summary.review_queue == 1
    assert (tmp_path / "generated/review_queue.jsonl").is_file()


def test_batch_resume_skips_existing_task(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    raw.mkdir(parents=True)
    (raw / "case-1.csv").write_text("case_id\ncase-1\n")
    (tmp_path / "tasks/case-1").mkdir(parents=True)
    summary = generate_all_cases(tmp_path, tmp_path / "tasks", client=FakeClient())
    assert summary.processed == 1
    assert summary.exported == 1
    assert summary.rejected == 0
