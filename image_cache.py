"""
Deprecated in v22.

Production images are now stored as optimized WebP bytes in PostgreSQL by
production_media.py.
"""


def get_cached_images(productions):
    return {}
