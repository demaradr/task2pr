from task2pr.store import TaskMapping, TaskMappingStore


def test_record_and_find_by_pr(tmp_path):
    store = TaskMappingStore(tmp_path / "state.json")
    mapping = TaskMapping(
        wrike_task_id="IEAAAAAA",
        github_owner="acme",
        github_repo="widgets",
        pr_number=42,
        branch="task2pr/fix-bug-abc123",
    )

    store.record(mapping)
    found = store.find_by_pr("acme", "widgets", 42)

    assert found == mapping


def test_find_by_pr_returns_none_when_not_found(tmp_path):
    store = TaskMappingStore(tmp_path / "state.json")
    assert store.find_by_pr("acme", "widgets", 1) is None


def test_store_creates_parent_directory(tmp_path):
    nested_path = tmp_path / "nested" / "dir" / "state.json"
    store = TaskMappingStore(nested_path)

    store.record(
        TaskMapping(
            wrike_task_id="X",
            github_owner="acme",
            github_repo="widgets",
            pr_number=1,
            branch="b",
        )
    )

    assert nested_path.exists()


def test_multiple_records_accumulate(tmp_path):
    store = TaskMappingStore(tmp_path / "state.json")
    store.record(TaskMapping("task-1", "acme", "widgets", 1, "b1"))
    store.record(TaskMapping("task-2", "acme", "widgets", 2, "b2"))

    assert store.find_by_pr("acme", "widgets", 1).wrike_task_id == "task-1"
    assert store.find_by_pr("acme", "widgets", 2).wrike_task_id == "task-2"
