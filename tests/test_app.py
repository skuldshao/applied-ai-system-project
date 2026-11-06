"""Smoke test: the Streamlit app loads without errors. Offline: no request is sent to the model."""

import logging
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "app.py"


def test_app_loads_with_the_ai_planner_section():
    logger = logging.getLogger("pawpal")
    before = list(logger.handlers)
    try:
        at = AppTest.from_file(str(APP), default_timeout=30).run()
        assert not at.exception
        assert any("AI Planner" in header.value for header in at.subheader)
    finally:
        # app.py calls setup_logging(); remove that file handler so later tests don't write
        # their fake runs into the real logs/pawpal.log.
        for handler in [h for h in logger.handlers if h not in before]:
            logger.removeHandler(handler)
            handler.close()
