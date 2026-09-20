import pytest

from task2pr.tools.filesystem import RepoSandbox, ToolError, grep, list_directory, read_file


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def greet():\n    return 'hi'\n")
    (tmp_path / "README.md").write_text("# demo repo\n")
    return tmp_path


@pytest.fixture
def sandbox(repo):
    return RepoSandbox(repo_root=repo)


def test_list_directory_lists_files_and_dirs(sandbox):
    result = list_directory(sandbox, ".")
    assert "README.md" in result
    assert "src/" in result


def test_read_file_returns_numbered_lines(sandbox):
    result = read_file(sandbox, "src/main.py")
    assert result.splitlines()[0] == "1\tdef greet():"


def test_read_file_windows_large_files(sandbox, repo):
    big_file = repo / "big.txt"
    big_file.write_text("\n".join(f"line{i}" for i in range(1000)))

    result = read_file(sandbox, "big.txt", offset=0, limit=10)

    lines = result.splitlines()
    assert len(lines) == 11  # 10 content lines + truncation note
    assert "line0" in lines[0]
    assert "990 more lines" in lines[-1]


def test_grep_finds_matches_recursively(sandbox):
    result = grep(sandbox, r"def greet")
    assert "src/main.py:1:def greet():" in result


def test_grep_no_matches(sandbox):
    assert grep(sandbox, r"nonexistent_pattern_xyz") == "(no matches)"


def test_sandbox_blocks_path_traversal(sandbox):
    with pytest.raises(ToolError, match="outside the target repo"):
        sandbox.resolve("../../etc/passwd")


def test_sandbox_blocks_absolute_path_escape(sandbox):
    with pytest.raises(ToolError, match="outside the target repo"):
        sandbox.resolve("/etc/passwd")


def test_read_file_missing_path_raises(sandbox):
    with pytest.raises(ToolError, match="does not exist"):
        read_file(sandbox, "nope.txt")
