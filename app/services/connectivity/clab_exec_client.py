"""
ContainerLab Exec Client

Sends commands to ContainerLab nodes via the clab-api-server exec endpoint.
Used by the grading worker when a Device has transport='docker_exec'.

Auth flow:  POST /login → JWT → Bearer {token}
Exec:       POST /api/v1/labs/{labName}/exec?nodeFilter={nodeName}
            Body: { "command": "<cmd>" }
            Response: Record<nodeName, ExecResult[]>
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    exit_code: int


class ClabExecClient:
    """Async HTTP client for clab-api-server exec operations."""

    def __init__(self, server_url: str, username: str, password: str) -> None:
        self._base_url = server_url.rstrip("/")
        self._username = username
        self._password = password
        self._token: Optional[str] = None
        # Monotonic time at which the token expires (seconds)
        self._token_expiry: float = 0.0

    async def _get_token(self) -> str:
        """Return a cached JWT, re-authenticating when it is near expiry."""
        now = time.monotonic()
        # Refresh 2 minutes before expiry to avoid races
        if self._token and now < self._token_expiry - 120:
            return self._token

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/login",
                json={"username": self._username, "password": self._password},
            )
            resp.raise_for_status()
            self._token = resp.json()["token"]
            # clab-api-server tokens are valid for 1 hour; we cache for 55 min
            self._token_expiry = now + 55 * 60

        return self._token  # type: ignore[return-value]

    async def exec_command(
        self,
        lab_name: str,
        node_name: str,
        command: str,
    ) -> CommandResult:
        """Execute a shell command on a specific ContainerLab node.

        Args:
            lab_name:  The deployed lab name (e.g. "student-abc123-ospf-lab")
            node_name: The node/container name within the lab (e.g. "router1")
            command:   Shell command to run (e.g. "ip route show")

        Returns:
            CommandResult with stdout, stderr, and exit_code.
        """
        token = await self._get_token()

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._base_url}/api/v1/labs/{lab_name}/exec",
                params={"nodeFilter": node_name},
                json={"command": command},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()

        data: dict = resp.json()

        # Response shape: { nodeName: [ { cmd, stdout, stderr, return-code } ] }
        results = data.get(node_name, [])
        if not results:
            logger.warning(
                "clab exec returned no results for node '%s' in lab '%s'",
                node_name,
                lab_name,
            )
            return CommandResult(stdout="", stderr="No output from node", exit_code=-1)

        first = results[0]
        return CommandResult(
            stdout=first.get("stdout", ""),
            stderr=first.get("stderr", ""),
            exit_code=first.get("return-code", 0),
        )


# ── Module-level singleton ────────────────────────────────────────────────────
# Initialised lazily so that import-time errors are avoided when the env vars
# are not yet set (e.g. during unit-test collection).

_client: Optional[ClabExecClient] = None


def get_clab_exec_client() -> ClabExecClient:
    """Return the shared ClabExecClient, creating it on first call."""
    global _client
    if _client is None:
        from app.core.config import config
        _client = ClabExecClient(
            server_url=config.CLAB_SERVER_URL,
            username=config.CLAB_ADMIN_USERNAME,
            password=config.CLAB_ADMIN_PASSWORD,
        )
    return _client
