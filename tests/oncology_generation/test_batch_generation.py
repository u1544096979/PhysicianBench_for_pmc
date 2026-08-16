from pathlib import Path

from scripts import generate_all_oncology_tasks as batch_module

generate_all_cases = batch_module.generate_all_cases

PILOT_CASE_IDS = (
    "71af50c891bd0e80cd017c8beb2bb446",
    "15c35bb60e48e62f9beb9fd127248e03",
    "7df4bd9af484dcec897b2f2726e01db2",
    "01864b911256ca7332f7974165d7aeb8",
    "aca554ac1716cf2fb7e2b94d80590e52",
)


class FakeClient:
    def chat(self, messages):
        raise RuntimeError("fake generation failure")


def test_batch_isolates_failures_and_writes_review_queue(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    raw.mkdir(parents=True)
    (raw / "case-1.csv").write_text("case_id\ncase-1\n")
    (raw / "case-2.csv").write_text("case_id\ncase-2\n")
    (tmp_path / "tasks/case-2").mkdir(parents=True)

    summary = generate_all_cases(tmp_path, tmp_path / "tasks", case_ids=["case-1", "case-2"], client=FakeClient())

    assert summary.processed == 2
    assert summary.exported == 1
    assert summary.rejected == 1
    assert summary.review_queue == 1
    assert (tmp_path / "generated/review_queue.jsonl").is_file()


def test_batch_resume_skips_existing_task(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    raw.mkdir(parents=True)
    (raw / "case-1.csv").write_text("case_id\ncase-1\n")
    (tmp_path / "tasks/case-1").mkdir(parents=True)
    summary = generate_all_cases(tmp_path, tmp_path / "tasks", case_ids=["case-1"], client=FakeClient())
    assert summary.processed == 1
    assert summary.exported == 1
    assert summary.rejected == 0


def test_batch_defaults_to_pilot_cases_and_ignores_other_csvs(tmp_path: Path):
    assert batch_module.PILOT_CASE_IDS == PILOT_CASE_IDS
    raw = tmp_path / "raw" / "csv"
    raw.mkdir(parents=True)
    for case_id in PILOT_CASE_IDS:
        (raw / f"{case_id}.csv").write_text("case_id\n" + case_id + "\n")
        (tmp_path / "tasks" / case_id).mkdir(parents=True)
    (raw / "not-a-pilot.csv").write_text("case_id\nnot-a-pilot\n")

    summary = generate_all_cases(tmp_path, tmp_path / "tasks", client=FakeClient())

    assert summary.processed == len(PILOT_CASE_IDS)
    assert summary.exported == len(PILOT_CASE_IDS)
    assert summary.rejected == 0


def test_batch_explicit_case_list_overrides_pilots(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    raw.mkdir(parents=True)
    (raw / "custom-case.csv").write_text("case_id\ncustom-case\n")
    (tmp_path / "tasks/custom-case").mkdir(parents=True)

    summary = generate_all_cases(
        tmp_path,
        tmp_path / "tasks",
        case_ids=["custom-case"],
        client=FakeClient(),
    )

    assert summary.processed == 1
    assert summary.exported == 1
    assert summary.rejected == 0
