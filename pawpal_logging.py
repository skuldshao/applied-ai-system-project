"""One place to set up logging for PawPal+.

Every PawPal+ module logs under the "pawpal" logger (e.g. "pawpal.llm"), and this module sends
those records to logs/pawpal.log. Only the "pawpal" logger is configured, never the root logger,
so Streamlit's own logging is left alone.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

LOG_FILE = Path(__file__).parent / "logs" / "pawpal.log"
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO, log_file: Union[str, Path] = LOG_FILE) -> None:
    """Send PawPal+ log records to a file, creating its folder if needed.

    Safe to call many times: Streamlit reruns the whole script on every click, and a second
    handler would write every line twice.

    Args:
        level: The lowest level to record. Defaults to INFO.
        log_file: Where to write. Defaults to logs/pawpal.log next to this file.
    """
    logger = logging.getLogger("pawpal")
    logger.setLevel(level)
    log_file = Path(log_file)
    if any(getattr(h, "baseFilename", None) == str(log_file.resolve()) for h in logger.handlers):
        return  # already logging to this file
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
