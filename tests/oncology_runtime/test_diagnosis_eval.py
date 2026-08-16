import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import run_eval
from utils.diagnosis_eval import evaluate_diagnosis_judge, evaluate_diagnosis_rules


TARGET_EVENTS = [
    {
        "_source_row": "12",
        "event_date": "2024-03-18",
        "source": "病理报告",
        "feature_name": "病理诊断",
        "value": "肺腺癌",
    },
    {
        "_source_row": "13",
        "event_date": "2024-03-18",
        "source": "病理报告",
        "feature_name": "分期",
        "value": "HER2 阳性",
    },
]


class FakeClient:
    def __init__(self, content: str | None = None, error: Exception | None = None):
        self.content = content
        self.error = error
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.error:
            raise self.error
        return type("Response", (), {"content": self.content})()


def test_run_eval_script_imports_project_modules_outside_repo_cwd(tmp_path: Path):
    script = Path(run_eval.__file__).resolve()

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_rules_classify_correct_with_unicode_normalization_and_removed_whitespace():
    result = evaluate_diagnosis_rules("结论：肺腺癌；HER2\u3000阳性。", TARGET_EVENTS)

    assert result["label"] == "correct"
    assert result["score"] == 1.0
    assert result["matched"] == [
        {"feature_name": "病理诊断", "value": "肺腺癌"},
        {"feature_name": "分期", "value": "HER2 阳性"},
    ]
    assert result["missing"] == []


def test_rules_classify_partially_correct():
    result = evaluate_diagnosis_rules("病理诊断考虑肺腺癌。", TARGET_EVENTS)

    assert result["label"] == "partially_correct"
    assert result["score"] == 0.5
    assert result["matched"] == [{"feature_name": "病理诊断", "value": "肺腺癌"}]
    assert result["missing"] == [{"feature_name": "分期", "value": "HER2 阳性"}]


def test_rules_classify_incorrect_without_scoring_date_or_source_metadata():
    result = evaluate_diagnosis_rules("病理报告日期 2024-03-18，来源行 12。", TARGET_EVENTS)

    assert result["label"] == "incorrect"
    assert result["score"] == 0.0
    assert result["matched"] == []
    assert result["missing"] == [
        {"feature_name": "病理诊断", "value": "肺腺癌"},
        {"feature_name": "分期", "value": "HER2 阳性"},
    ]


@pytest.mark.parametrize(
    "content",
    [
        '{"label":"correct","score":1,"reason":"诊断和分期均一致"}',
        '```json\n{"label":"partially_correct","score":0.5,"reason":"仅诊断一致"}\n```',
    ],
)
def test_judge_parses_plain_and_fenced_json(content):
    client = FakeClient(content=content)

    result = evaluate_diagnosis_judge("肺腺癌", TARGET_EVENTS, client)

    assert result["label"] in {"correct", "partially_correct"}
    assert isinstance(result["score"], float)
    assert result["reason"]
    messages, kwargs = client.calls[0]
    prompt = messages[-1]["content"]
    assert "GROUND_TRUTH_TARGET_EVENTS" in prompt
    assert "AGENT_FINAL_OUTPUT" in prompt
    assert kwargs["temperature"] == 0
    assert kwargs["tools"] is None


def test_judge_rejects_non_object_json():
    with pytest.raises(ValueError, match="JSON object"):
        evaluate_diagnosis_judge("肺腺癌", TARGET_EVENTS, FakeClient(content='["correct"]'))


def test_evaluation_file_records_judge_call_failure_as_evaluator_error(tmp_path: Path):
    task_dir = tmp_path / "task"
    job_dir = tmp_path / "job"
    task_dir.mkdir()
    (task_dir / "ground_truth.json").write_text(
        json.dumps({"target_events": TARGET_EVENTS}, ensure_ascii=False),
        encoding="utf-8",
    )
    stdout = job_dir / "logs" / "agent" / "stdout.txt"
    stdout.parent.mkdir(parents=True)
    stdout.write_text("肺腺癌；HER2 阳性", encoding="utf-8")

    output_path = run_eval.write_diagnosis_evaluation(
        task_dir,
        job_dir,
        client=FakeClient(error=RuntimeError("judge unavailable")),
    )

    assert output_path == job_dir / "logs" / "verifier" / "diagnosis_eval.json"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["rule"]["label"] == "correct"
    assert payload["judge"] is None
    assert payload["evaluator_error"]["stage"] == "judge_call"
    assert "judge unavailable" in payload["evaluator_error"]["message"]
    assert payload.get("label") != "incorrect"


def test_evaluation_file_records_judge_parse_failure(tmp_path: Path):
    task_dir = tmp_path / "task"
    job_dir = tmp_path / "job"
    task_dir.mkdir()
    (task_dir / "ground_truth.json").write_text(
        json.dumps({"target_events": TARGET_EVENTS}, ensure_ascii=False),
        encoding="utf-8",
    )
    stdout = job_dir / "logs" / "agent" / "stdout.txt"
    stdout.parent.mkdir(parents=True)
    stdout.write_text("肺腺癌", encoding="utf-8")

    output_path = run_eval.write_diagnosis_evaluation(
        task_dir,
        job_dir,
        client=FakeClient(content='["not-an-object"]'),
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["rule"]["label"] == "partially_correct"
    assert payload["judge"] is None
    assert payload["evaluator_error"]["stage"] == "judge_parse"
