"""Session-wide guard: no test may reach real AWS, or wait on a real network.

Without this, botocore resolves credentials the way it would in production:
environment, then shared config, then container, then the EC2 instance metadata
service at 169.254.169.254. Off EC2 that last hop has nobody to answer it, so it
waits for a connect timeout and retries before giving up. Every client built
outside a moto mock pays that -- `composition_test` builds three and spent 17 of
its 23 seconds there.

Speed is the smaller reason. The larger one is that a developer or CI runner who
happens to hold real credentials would otherwise have those clients resolve
them, so a test that escaped its mock would talk to a real account instead of
failing. Fake credentials here mean such a test fails loudly and locally.

moto already sets its own fake credentials inside `mock_aws`, so this changes
nothing for mocked tests; it covers the ones that construct clients without one.
"""

import os

import pytest

_FAKE_AWS_ENVIRONMENT = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "ap-south-1",
    # Stops the metadata hop being attempted at all, rather than merely being
    # reached last: credentials found in the environment short-circuit it, but
    # region and IMDSv2 token lookups can still probe the endpoint.
    "AWS_EC2_METADATA_DISABLED": "true",
}


@pytest.fixture(scope="session", autouse=True)
def _never_reach_real_aws() -> None:
    """Applied once for the session, before any module builds a client."""
    for name, value in _FAKE_AWS_ENVIRONMENT.items():
        os.environ[name] = value
