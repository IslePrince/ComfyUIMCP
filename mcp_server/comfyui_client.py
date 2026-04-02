import asyncio
import json
import uuid
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

CANDIDATE_PORTS = [8000, 8001, 8002]


class ComfyUIClient:
    """Async client for ComfyUI REST + WebSocket API."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url  # resolved lazily if None
        self._session: aiohttp.ClientSession | None = None
        self._client_id = str(uuid.uuid4())
        self.jobs: dict[str, dict[str, Any]] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _resolve_url(self) -> str:
        """Auto-detect ComfyUI port if base_url not confirmed working."""
        if self.base_url:
            try:
                session = await self._get_session()
                async with session.get(
                    f"{self.base_url}/system_stats", timeout=aiohttp.ClientTimeout(total=3)
                ) as resp:
                    if resp.status == 200:
                        return self.base_url
            except Exception:
                pass

        # Try candidate ports
        session = await self._get_session()
        # Extract host from base_url or default
        host = "host.docker.internal"
        if self.base_url:
            from urllib.parse import urlparse
            parsed = urlparse(self.base_url)
            host = parsed.hostname or host

        for port in CANDIDATE_PORTS:
            url = f"http://{host}:{port}"
            try:
                async with session.get(
                    f"{url}/system_stats", timeout=aiohttp.ClientTimeout(total=3)
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"Found ComfyUI at {url}")
                        self.base_url = url
                        return url
            except Exception:
                continue

        raise ConnectionError(
            f"Cannot reach ComfyUI on any of ports {CANDIDATE_PORTS}. "
            "Ensure ComfyUI is running."
        )

    async def ensure_connected(self) -> str:
        """Ensure we have a valid base_url. Returns the URL."""
        return await self._resolve_url()

    async def queue_prompt(self, workflow: dict) -> str:
        """Queue a workflow for execution. Returns prompt_id."""
        url = await self.ensure_connected()
        session = await self._get_session()
        payload = {
            "prompt": workflow,
            "client_id": self._client_id,
        }
        async with session.post(f"{url}/prompt", json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"ComfyUI rejected prompt: {resp.status} {text}")
            data = await resp.json()
            prompt_id = data["prompt_id"]
            self.jobs[prompt_id] = {
                "status": "queued",
                "progress": 0.0,
                "result_files": [],
                "error": None,
            }
            return prompt_id

    async def get_history(self, prompt_id: str) -> dict:
        """Get execution history for a prompt."""
        url = await self.ensure_connected()
        session = await self._get_session()
        async with session.get(f"{url}/history/{prompt_id}") as resp:
            data = await resp.json()
            return data.get(prompt_id, {})

    async def get_image_bytes(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        """Download a generated file from ComfyUI."""
        url = await self.ensure_connected()
        session = await self._get_session()
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        async with session.get(f"{url}/view", params=params) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to fetch {filename}: {resp.status}")
            return await resp.read()

    async def upload_image(self, image_bytes: bytes, filename: str, subfolder: str = "", overwrite: bool = True) -> dict:
        """Upload an image to ComfyUI's input directory."""
        url = await self.ensure_connected()
        session = await self._get_session()
        form = aiohttp.FormData()
        form.add_field("image", image_bytes, filename=filename, content_type="image/png")
        form.add_field("subfolder", subfolder)
        form.add_field("overwrite", str(overwrite).lower())
        async with session.post(f"{url}/upload/image", data=form) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to upload {filename}: {resp.status}")
            return await resp.json()

    async def get_system_stats(self) -> dict:
        """Get ComfyUI system stats (health check)."""
        url = await self.ensure_connected()
        session = await self._get_session()
        async with session.get(f"{url}/system_stats") as resp:
            return await resp.json()

    async def wait_for_completion(self, prompt_id: str, timeout: float = 600) -> dict:
        """Wait for a prompt to complete using WebSocket monitoring. Returns history."""
        url = await self.ensure_connected()
        ws_url = url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/ws?clientId={self._client_id}"

        try:
            session = await self._get_session()
            async with session.ws_connect(ws_url) as ws:
                start = asyncio.get_event_loop().time()
                async for msg in ws:
                    if asyncio.get_event_loop().time() - start > timeout:
                        self.jobs[prompt_id]["status"] = "failed"
                        self.jobs[prompt_id]["error"] = "Timeout"
                        raise TimeoutError(f"Generation timed out after {timeout}s")

                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        msg_type = data.get("type")
                        msg_data = data.get("data", {})

                        if msg_data.get("prompt_id") != prompt_id:
                            continue

                        if msg_type == "progress":
                            value = msg_data.get("value", 0)
                            max_val = msg_data.get("max", 1)
                            self.jobs[prompt_id]["status"] = "running"
                            self.jobs[prompt_id]["progress"] = value / max_val if max_val else 0

                        elif msg_type == "executed":
                            self.jobs[prompt_id]["status"] = "completed"
                            self.jobs[prompt_id]["progress"] = 1.0
                            # Fetch history for output files
                            history = await self.get_history(prompt_id)
                            outputs = history.get("outputs", {})
                            files = []
                            for node_outputs in outputs.values():
                                for key in ("images", "gifs", "videos"):
                                    for item in node_outputs.get(key, []):
                                        files.append(item)
                            self.jobs[prompt_id]["result_files"] = files
                            return history

                        elif msg_type == "execution_error":
                            self.jobs[prompt_id]["status"] = "failed"
                            self.jobs[prompt_id]["error"] = str(msg_data)
                            raise RuntimeError(f"Execution error: {msg_data}")

                    elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                        break

        except aiohttp.ClientError as e:
            logger.warning(f"WebSocket error, falling back to polling: {e}")
            return await self._poll_for_completion(prompt_id, timeout)

    async def _poll_for_completion(self, prompt_id: str, timeout: float = 600) -> dict:
        """Fallback: poll /history until the prompt completes."""
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            history = await self.get_history(prompt_id)
            if history:
                status = history.get("status", {})
                if status.get("completed", False) or "outputs" in history:
                    self.jobs[prompt_id]["status"] = "completed"
                    self.jobs[prompt_id]["progress"] = 1.0
                    outputs = history.get("outputs", {})
                    files = []
                    for node_outputs in outputs.values():
                        for key in ("images", "gifs", "videos"):
                            for item in node_outputs.get(key, []):
                                files.append(item)
                    self.jobs[prompt_id]["result_files"] = files
                    return history
                if status.get("status_str") == "error":
                    self.jobs[prompt_id]["status"] = "failed"
                    self.jobs[prompt_id]["error"] = str(status.get("messages", "Unknown error"))
                    raise RuntimeError(f"Execution failed: {status}")
            await asyncio.sleep(2)
        raise TimeoutError(f"Generation timed out after {timeout}s")

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
