import base64
import os
import uuid

from fastmcp import FastMCP


def register_catalog_tools(mcp: FastMCP, catalog, client):
    @mcp.tool()
    async def list_capabilities() -> dict:
        """List all available generation capabilities with their parameters.
        Use this to discover what image/video generation workflows are available."""
        caps = catalog.list_capabilities()
        return {
            "capabilities": [cap.model_dump() for cap in caps],
            "comfyui_status": "checking...",
        }

    @mcp.tool()
    async def health_check() -> dict:
        """Check if ComfyUI is running and accessible."""
        try:
            stats = await client.get_system_stats()
            return {"status": "ok", "comfyui": stats}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @mcp.tool()
    async def upload_image(image_base64: str, filename: str = "") -> dict:
        """Upload an image to ComfyUI so it can be used with image_to_video or image_to_image.

        Returns the filename to pass as the 'image' or 'image_path' parameter to other tools.

        Args:
            image_base64: The image data encoded as a base64 string
            filename: Optional filename (auto-generated if empty). Must end in .png, .jpg, or .webp.
        """
        try:
            image_bytes = base64.b64decode(image_base64)
        except Exception:
            return {"error": "Invalid base64 data"}

        if not filename:
            filename = f"mcp_upload_{uuid.uuid4().hex[:8]}.png"

        # Save locally so Docker-mounted tools can find it
        input_dir = os.environ.get("INPUT_DIR", "/app/input")
        os.makedirs(input_dir, exist_ok=True)
        local_path = os.path.join(input_dir, filename)
        with open(local_path, "wb") as f:
            f.write(image_bytes)

        # Also upload to ComfyUI's input directory
        try:
            result = await client.upload_image(image_bytes, filename)
            comfyui_name = result.get("name", filename)
        except Exception as e:
            return {"error": f"Failed to upload to ComfyUI: {e}"}

        return {
            "filename": comfyui_name,
            "size_bytes": len(image_bytes),
            "message": f"Image uploaded. Use '{comfyui_name}' as the image parameter in image_to_video or image_to_image.",
        }
