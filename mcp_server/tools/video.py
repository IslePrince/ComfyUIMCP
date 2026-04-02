import asyncio
import os
from typing import Any

from fastmcp import FastMCP


def register_video_tools(mcp: FastMCP, catalog, client):
    @mcp.tool()
    async def image_to_video(
        image_path: str,
        prompt: str = "",
        negative_prompt: str = "",
        length: int = 81,
        width: int = 640,
        height: int = 960,
        seed: int = -1,
    ) -> dict:
        """Convert an image to a video/animation using Wan2.2 I2V with LightX2V.

        Great for animating tarot cards, character art, or any still image.
        Uses 4-step distillation for fast generation.

        Args:
            image_path: Path to the input image (in the input/ directory)
            prompt: Text prompt to guide the animation
            negative_prompt: What to avoid in the video
            length: Number of frames (81 = ~5 seconds at 16fps)
            width: Video width (default 640)
            height: Video height (default 960 for portrait/tarot)
            seed: Random seed (-1 for random)
        """
        # Try to find and upload the image, or use the filename directly
        # (it may already be in ComfyUI's input dir via upload_image tool)
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
            # Assume it's already in ComfyUI's input directory
            image_name = os.path.basename(image_path)

        params: dict[str, Any] = {
            "image": image_name,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "length": length,
            "width": width,
            "height": height,
            "seed": seed,
        }

        try:
            workflow = catalog.build_prompt("image_to_video", params)
        except ValueError as e:
            return {"error": str(e)}

        prompt_id = await client.queue_prompt(workflow)

        # Video generation can be slow, track in background
        asyncio.create_task(_wait_and_store(client, prompt_id))

        return {
            "prompt_id": prompt_id,
            "status": "queued",
            "message": f"Video generation started (this may take several minutes). Use get_status('{prompt_id}') to check progress.",
        }


async def _wait_and_store(client, prompt_id: str):
    try:
        await client.wait_for_completion(prompt_id, timeout=1200)  # 20min timeout for video
    except Exception as e:
        client.jobs[prompt_id]["status"] = "failed"
        client.jobs[prompt_id]["error"] = str(e)
