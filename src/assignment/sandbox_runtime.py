"""SWE-ReX JSON requests that respect the local HTTP proxy configuration."""

from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any

import aiohttp
from pydantic import BaseModel
from swerex.runtime.abstract import IsAliveResponse
from swerex.runtime.remote import RemoteRuntime


class AssignmentRemoteRuntime(RemoteRuntime):
    """Use environment proxies for health checks and command requests.

    SWE-ReX 1.4.0 creates aiohttp sessions with trust_env disabled. A local
    proxy may be needed to resolve and reach Modal tunnel hosts. Keep the
    upstream authentication, response decoding, and request IDs.
    """

    def _session(self, timeout: float | None = None) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(force_close=True),
            timeout=aiohttp.ClientTimeout(total=self._get_timeout(timeout)),
            trust_env=True,
        )

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        try:
            async with self._session(timeout) as session:
                async with session.get(
                    f"{self._api_url}/is_alive", headers=self._headers
                ) as response:
                    await self._handle_response_errors(response)
                    return IsAliveResponse(**await response.json())
        except Exception as exc:
            return IsAliveResponse(
                is_alive=False,
                message=f"Runtime health check failed ({type(exc).__name__}).",
            )

    async def _request(
        self,
        endpoint: str,
        payload: BaseModel | None,
        output_class: Any,
        num_retries: int = 0,
    ):
        headers = self._headers.copy()
        # Reuse the ID on retries so the server does not execute a command twice.
        headers["X-Request-ID"] = str(uuid.uuid4())
        retry_delay = 0.1
        for attempt in range(num_retries + 1):
            try:
                async with self._session() as session:
                    async with session.post(
                        f"{self._api_url}/{endpoint}",
                        json=payload.model_dump() if payload else None,
                        headers=headers,
                    ) as response:
                        await self._handle_response_errors(response)
                        return output_class(**await response.json())
            except Exception:
                if attempt == num_retries:
                    raise
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2 + random.uniform(0, 0.5), 5)
