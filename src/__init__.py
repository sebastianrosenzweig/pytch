import logging
try:  # Python 2.7+
    from logging import NullHandler
except ImportError:
    class NullHandler(logging.Handler):
        def emit(self, record):
            pass

logging.basicConfig(level=logging.INFO)
logging.getLogger(__name__).addHandler(NullHandler())
