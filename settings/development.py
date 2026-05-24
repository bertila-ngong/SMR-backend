import os

os.environ.setdefault("PAPERLESS_DEBUG", "yes")
os.environ.setdefault("PAPERLESS_SECRET_KEY", "development-secret-key")

from .base import *  # noqa: F403
