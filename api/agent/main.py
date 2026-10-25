"""Main Sequence Harness Agent entry point: the one Hunch Agent.

The `hunch-agent` workflow declaration points its `source_path` here, so this file stays at this
path. It is not part of the wheel.

`ms_tau_sdk.create_app()` builds the Tau runtime for this workspace and installs the request
identity that the platform's launcher requires. The launcher reads that declaration from the object
it serves, so `app` must be the object `create_app()` returns, never an application that mounts it.
The project tools come from the `hunch` API's MCP, which the workflow declares for this Agent; the
Agent never calls a venue connector itself.
"""

from ms_tau_sdk import create_app

app = create_app()

__all__ = ["app"]
