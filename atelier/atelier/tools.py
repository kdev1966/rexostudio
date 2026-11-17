import os


def ensure_parent(path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path
