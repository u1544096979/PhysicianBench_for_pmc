import json
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


def _write_complete_task(task_dir: Path, case_id: str) -> None:
    task_dir.mkdir(parents=True)
    (task_dir / "instruction.md").write_text("Assess the diagnosis.\n", encoding="utf-8")
    (task_dir / "task.toml").write_text(
        f'[metadata]\ncase_id = "{case_id}"\ndata_root = "../../../data/cleaned"\ntags = ["Oncology"]\n',
        encoding="utf-8",
    )
    (task_dir / "ground_truth.json").write_text(
        json.dumps(
            {
                "case_id": case_id,
                "target_group_id": "g1",
                "target_event_date": "2024-01-01",
                "source_rows": ["2"],
                "target_events": [{}],
            }
        ),
        encoding="utf-8",
    )
    (task_dir / "tests").mkdir()
    (task_dir / "tests/test_outputs.py").write_text("def test_output():\n    pass\n", encoding="utf-8")


def test_batch_isolates_failures_and_writes_review_queue(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    raw.mkdir(parents=True)
    (raw / "case-1.csv").write_text("case_id\ncase-1\n")
    (raw / "case-2.csv").write_text("case_id\ncase-2\n")
    _write_complete_task(tmp_path / "tasks/case-2", "case-2")

    summary = generate_all_cases(tmp_path, tmp_path / "tasks", case_ids=["case-1", "case-2"], client=FakeClient())

    assert summary.processed == 2
    assert summary.exported == 1
    assert summary.rejected == 1
    assert summary.review_queue == 1
    review_path = tmp_path / "generated/review_queue.jsonl"
    assert review_path.is_file()
    state_path = tmp_path / "generated/case-1/state.json"
    assert state_path.is_file()
    state = json.loads(state_path.read_text())
    assert state["case_id"] == "case-1"
    assert state["error"] == summary.errors["case-1"]
    assert state["error"]
    review_item = json.loads(review_path.read_text().splitlines()[0])
    assert review_item["state_path"] == str(state_path)


def test_batch_resume_skips_existing_task(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    raw.mkdir(parents=True)
    (raw / "case-1.csv").write_text("case_id\ncase-1\n")
    _write_complete_task(tmp_path / "tasks/case-1", "case-1")
    summary = generate_all_cases(tmp_path, tmp_path / "tasks", case_ids=["case-1"], client=FakeClient())
    assert summary.processed == 1
    assert summary.exported == 1
    assert summary.rejected == 0


def test_batch_does_not_resume_incomplete_task(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    raw.mkdir(parents=True)
    (raw / "case-1.csv").write_text("case_id\ncase-1\n")
    task_dir = tmp_path / "tasks/case-1"
    task_dir.mkdir(parents=True)
    (task_dir / "instruction.md").write_text("partial\n", encoding="utf-8")

    summary = generate_all_cases(tmp_path, tmp_path / "tasks", case_ids=["case-1"], client=FakeClient())

    assert summary.processed == 1
    assert summary.exported == 0
    assert summary.rejected == 1
    assert (tmp_path / "generated/case-1/state.json").is_file()


def test_batch_does_not_resume_unparseable_task(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    raw.mkdir(parents=True)
    (raw / "case-1.csv").write_text("case_id\ncase-1\n")
    task_dir = tmp_path / "tasks/case-1"
    _write_complete_task(task_dir, "case-1")
    (task_dir / "task.toml").write_text("not valid toml = [", encoding="utf-8")

    summary = generate_all_cases(tmp_path, tmp_path / "tasks", case_ids=["case-1"], client=FakeClient())

    assert summary.exported == 0
    assert summary.rejected == 1


def test_batch_defaults_to_pilot_cases_and_ignores_other_csvs(tmp_path: Path):
    assert batch_module.PILOT_CASE_IDS == PILOT_CASE_IDS
    raw = tmp_path / "raw" / "csv"
    raw.mkdir(parents=True)
    for case_id in PILOT_CASE_IDS:
        (raw / f"{case_id}.csv").write_text("case_id\n" + case_id + "\n")
        _write_complete_task(tmp_path / "tasks" / case_id, case_id)
    (raw / "not-a-pilot.csv").write_text("case_id\nnot-a-pilot\n")

    summary = generate_all_cases(tmp_path, tmp_path / "tasks", client=FakeClient())

    assert summary.processed == len(PILOT_CASE_IDS)
    assert summary.exported == len(PILOT_CASE_IDS)
    assert summary.rejected == 0


def test_batch_explicit_case_list_overrides_pilots(tmp_path: Path):
    raw = tmp_path / "raw" / "csv"
    raw.mkdir(parents=True)
    (raw / "custom-case.csv").write_text("case_id\ncustom-case\n")
    _write_complete_task(tmp_path / "tasks/custom-case", "custom-case")

    summary = generate_all_cases(
        tmp_path,
        tmp_path / "tasks",
        case_ids=["custom-case"],
        client=FakeClient(),
    )

    assert summary.processed == 1
    assert summary.exported == 1
    assert summary.rejected == 0
