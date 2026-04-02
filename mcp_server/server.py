import logging
import os
import sys

from fastmcp import FastMCP

from catalog import Catalog
from comfyui_client import ComfyUIClient
from tools.catalog_tools import register_catalog_tools
from tools.generate import register_generate_tools
from tools.video import register_video_tools
from tools.status import register_status_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize shared instances
comfyui_url = os.environ.get("COMFYUI_URL", "http://host.docker.internal:8000")
workflows_dir = os.environ.get("WORKFLOWS_DIR", "/app/workflows")

# Allow local dev by checking if workflows dir exists at relative path
if not os.path.exists(workflows_dir):
    local_workflows = os.path.join(os.path.dirname(__file__), "..", "workflows")
    if os.path.exists(local_workflows):
        workflows_dir = local_workflows

client = ComfyUIClient(base_url=comfyui_url)
catalog = Catalog(workflows_dir=workflows_dir)

# Create MCP server
mcp = FastMCP(
    "ComfyUI",
    instructions=(
        "ComfyUI MCP server for AI image and video generation. "
        "Use list_capabilities to see available workflows. "
        "Use generate_image for text-to-image, or generate for any capability. "
        "Jobs are async: queue with generate, check with get_status, retrieve with get_result."
    ),
)

# Register all tool groups
register_catalog_tools(mcp, catalog, client)
register_generate_tools(mcp, catalog, client)
register_video_tools(mcp, catalog, client)
register_status_tools(mcp, catalog, client)

if __name__ == "__main__":
    port = int(os.environ.get("MCP_PORT", "8199"))
    logger.info(f"Starting ComfyUI MCP server on port {port}")
    logger.info(f"ComfyUI URL: {comfyui_url}")
    logger.info(f"Workflows dir: {workflows_dir}")
    logger.info(f"Loaded {len(catalog.capabilities)} capabilities: {list(catalog.capabilities.keys())}")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
