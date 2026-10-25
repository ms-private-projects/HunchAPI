"""FastAPI entrypoint discovered from the CodeRepository's top-level api directory.

The `hunch` workflow declaration points its `source_path` here, so this file stays at this path.
It is not part of the wheel. The application itself is built by `hunch.api.app.main.create_app`,
which installs the Main Sequence request identity the platform's launcher requires.
"""

from hunch.api.app.main import app

__all__ = ["app"]
