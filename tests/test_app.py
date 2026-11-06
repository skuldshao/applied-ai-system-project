"""Smoke test: the Streamlit app loads without errors. Offline: no request is sent to the model."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "app.py"


def test_app_loads_with_the_ai_planner_section():
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    assert any("AI Planner" in header.value for header in at.subheader)
