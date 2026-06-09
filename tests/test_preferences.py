from jobhunter.preferences import (
    adaptive_preference_questions,
    load_preferences,
    parse_preference_assignment,
    save_preferences,
    update_preferences,
)
from jobhunter.profile import build_user_profile


def test_adaptive_questions_reflect_missing_preferences():
    profile = build_user_profile("Machine Learning Engineer and Software Engineer with Python LLM.")

    questions = adaptive_preference_questions(profile, limit=8)

    question_ids = [question.id for question in questions]

    assert question_ids[:3] == ["target_roles", "preferred_locations", "remote"]
    assert "result_count" in question_ids
    assert "output_format" in question_ids


def test_adaptive_questions_ask_about_portfolio_focus_when_multiple_highlights_exist():
    profile = build_user_profile(
        """# Ada Chen
Research Scientist

## Current Projects
* Built an agentic memory system for long-context model evaluation.
* Published a forecasting benchmark with tabular and relational data.
"""
    )

    questions = adaptive_preference_questions(profile)

    assert questions[0].id == "focus_highlights"
    assert questions[0].examples


def test_preferences_can_be_updated_and_saved(tmp_path):
    profile = build_user_profile("Python LLM engineer.")
    prefs = update_preferences(
        profile.preferences,
        dict(
            [
                parse_preference_assignment("preferred_locations=Remote US,New York"),
                parse_preference_assignment("remote=true"),
                parse_preference_assignment("min_salary=160000"),
                parse_preference_assignment("focus_highlights=agentic memory,long-context evaluation"),
                parse_preference_assignment("result_count=25"),
                parse_preference_assignment("output_format=json"),
            ]
        ),
    )
    path = tmp_path / "prefs.json"

    save_preferences(path, prefs)
    loaded = load_preferences(path)

    assert loaded.preferred_locations == ("Remote US", "New York")
    assert loaded.remote is True
    assert loaded.min_salary == 160000
    assert loaded.focus_highlights == ("agentic memory", "long-context evaluation")
    assert loaded.result_count == 25
    assert loaded.output_format == "json"
