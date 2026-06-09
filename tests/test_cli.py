from io import StringIO
from contextlib import redirect_stdout

from jobhunter.cli import main


def test_cli_defaults_to_tsv_output_for_search_results():
    output = StringIO()

    with redirect_stdout(output):
        status = main(["--input", "Machine Learning Engineer with Python LLM. Remote.", "--offline", "--limit", "1"])

    lines = output.getvalue().splitlines()
    assert status == 0
    assert lines[0].startswith("rank\tscore\ttitle\tcompany")
    assert len(lines) == 2


def test_cli_show_questions_remains_human_readable_before_search():
    output = StringIO()

    with redirect_stdout(output):
        status = main(
            [
                "--input",
                "Machine Learning Engineer and Software Engineer with Python LLM.",
                "--offline",
                "--show-questions",
                "--limit",
                "1",
            ]
        )

    text = output.getvalue()
    assert status == 0
    assert "Adaptive questions" in text
    assert "result_count" in text
    assert "output_format" in text
