import asyncio
import base64
import os
from typing import Any

from fastmcp import FastMCP


def register_generate_tools(mcp: FastMCP, catalog, client):
    @mcp.tool()
    async def generate_image(
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        cfg_scale: float = 7.0,
        seed: int = -1,
        checkpoint: str = "",
    ) -> dict:
        """Generate an image from a text prompt using ComfyUI.

        Args:
            prompt: Text description of the desired image
            negative_prompt: What to avoid in the image
            width: Image width in pixels (512, 768, 1024, 1280)
            height: Image height in pixels (512, 768, 1024, 1280)
            steps: Number of sampling steps (1-50, default 20)
            cfg_scale: Classifier-free guidance scale (default 7.0)
            seed: Random seed (-1 for random)
            checkpoint: Model checkpoint name (empty for default)
        """
        params: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "seed": seed,
        }
        if checkpoint:
            params["checkpoint"] = checkpoint

        try:
            workflow = catalog.build_prompt("text_to_image", params)
        except ValueError as e:
            return {"error": str(e)}

        prompt_id = await client.queue_prompt(workflow)

        # Wait for completion in background, but return immediately
        asyncio.create_task(_wait_and_store(client, prompt_id))

        return {
            "prompt_id": prompt_id,
            "status": "queued",
            "message": "Image generation started. Use get_status to check progress, then get_result to retrieve the image.",
        }

    @mcp.tool()
    async def generate(capability: str, params: dict[str, Any] = {}) -> dict:
        """Run any generation workflow by capability name.

        Use list_capabilities first to see available capabilities and their parameters.

        Args:
            capability: Name of the capability (e.g. 'text_to_image', 'upscale', 'inpainting')
            params: Dictionary of parameters matching the capability's parameter definitions
        """
        try:
            workflow = catalog.build_prompt(capability, params)
        except ValueError as e:
            return {"error": str(e)}

        prompt_id = await client.queue_prompt(workflow)
        asyncio.create_task(_wait_and_store(client, prompt_id))

        return {
            "prompt_id": prompt_id,
            "status": "queued",
            "capability": capability,
            "message": f"Generation started. Use get_status('{prompt_id}') to check progress.",
        }

    @mcp.tool()
    async def image_to_image(
        image_path: str,
        prompt: str,
        strength: float = 0.75,
        negative_prompt: str = "",
        steps: int = 20,
        cfg_scale: float = 7.0,
        seed: int = -1,
    ) -> dict:
        """Transform an existing image using a text prompt.

        Args:
            image_path: Path to the input image (in the input/ directory)
            prompt: Text description of desired transformation
            strength: How much to change the image (0.0-1.0, higher = more change)
            negative_prompt: What to avoid
            steps: Sampling steps
            cfg_scale: Guidance scale
            seed: Random seed (-1 for random)
        """
        # Try to find and upload the image, or use the filename directly
        input_dir = os.environ.get("INPUT_DIR", "/app/input")
        full_path = os.path.join(input_dir, os.path.basename(image_path))
        if not os.path.exists(full_path):
            full_path = image_path

        if os.path.exists(full_path):
            with open(full_path, "rb") as f:
                image_bytes = f.read()
            filename = os.path.basename(full_path)
            upload_result = await client.upload_image(image_bytes, filename)
            image_name = upload_result.get("name", filename)
        else:
            image_name = os.path.basename(image_path)

        params = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "image": image_name,
            "strength": strength,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "seed": seed,
        }

        try:
            workflow = catalog.build_prompt("image_to_image", params)
        except ValueError as e:
            return {"error": str(e)}

        prompt_id = await client.queue_prompt(workflow)
        asyncio.create_task(_wait_and_store(client, prompt_id))

        return {
            "prompt_id": prompt_id,
            "status": "queued",
            "message": f"Image-to-image started. Use get_status('{prompt_id}') to check progress.",
        }


async def _wait_and_store(client, prompt_id: str):
    """Background task to track completion via WebSocket."""
    try:
        await client.wait_for_completion(prompt_id, timeout=600)
    except Exception as e:
        client.jobs[prompt_id]["status"] = "failed"
        client.jobs[prompt_id]["error"] = str(e)
