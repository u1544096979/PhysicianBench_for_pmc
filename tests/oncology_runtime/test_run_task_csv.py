from scripts import run_task


def test_csv_run_agent_signature_accepts_data_root():
    assert "data_root" in run_task.run_agent.__annotations__
    assert run_task.run_evaluation.__defaults__ == (None,)


def test_csv_default_data_path_is_project_relative():
    root = run_task.REPO_ROOT / "data" / "oncology_complete_trajectory"
    assert root.name == "oncology_complete_trajectory"
