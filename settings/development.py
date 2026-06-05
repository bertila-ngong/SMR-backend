import os

os.environ.setdefault("PAPERLESS_DEBUG", "yes")
os.environ.setdefault("PAPERLESS_SECRET_KEY", "development-secret-key")
os.environ.setdefault("PAPERLESS_OCR_CLEAN", "none")

from .base import *  # noqa: F403
