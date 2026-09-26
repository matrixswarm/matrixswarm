"""Log traceback locations without exception payloads, source lines or locals."""
import logging
import traceback


def log_exception_locations(operation, error):
    locations = "\n".join(f"{frame.filename}:{frame.lineno} in {frame.name}"
                          for frame in traceback.extract_tb(error.__traceback__))
    logging.getLogger(__name__).error("%s failed (%s)\n%s", operation, type(error).__name__, locations)
