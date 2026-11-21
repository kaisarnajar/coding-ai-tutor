import logging
import sys

logger = logging.getLogger("tutor")

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [backend] %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def block(text: str) -> str:
    """Return the full text on its own lines, indented under the log line."""
    return "".join(f"\n      {line}" for line in text.splitlines() or [""])
