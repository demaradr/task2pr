from task2pr.tools.test_runner import run_tests


def test_run_tests_passes_on_zero_exit(tmp_path):
    result = run_tests("python3 -c \"import sys; sys.exit(0)\"", tmp_path)
    assert result.passed
    assert result.returncode == 0


def test_run_tests_fails_on_nonzero_exit(tmp_path):
    result = run_tests(
        "python3 -c \"import sys; print('boom'); sys.exit(1)\"", tmp_path
    )
    assert not result.passed
    assert result.returncode == 1
    assert "boom" in result.output


def test_run_tests_reports_missing_command(tmp_path):
    result = run_tests("this-command-does-not-exist-xyz", tmp_path)
    assert not result.passed
    assert "Could not run test command" in result.output


def test_run_tests_truncates_long_output(tmp_path):
    result = run_tests(
        "python3 -c \"print('x' * 20000)\"", tmp_path,
    )
    assert len(result.output) < 20000
    assert "truncated" in result.output
