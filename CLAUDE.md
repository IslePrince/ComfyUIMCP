# ComfyUI MCP Wrapper

## What This Is
An MCP server that wraps a local ComfyUI instance, exposing image/video generation as tools for Claude Code.

## Architecture
- MCP server runs in Docker (port 8199)
- Connects to local ComfyUI (ports 8000/8001/8002, auto-detected)
- Workflow templates in `workflows/` define available capabilities
- Generated files land in `output/`, input images go in `input/`

## Running
```bash
docker compose up -d
```

## Adding New Workflows
1. Build and test workflow in ComfyUI browser UI
2. Save as API format JSON
3. Create `workflows/<name>/workflow.json` and `manifest.yaml`
4. Restart: `docker compose restart mcp`

## MCP Tools
- `list_capabilities` - browse available generation types
- `generate_image` - text-to-image shortcut
- `generate` - run any workflow by capability name
- `image_to_video` - convert image to video
- `get_status` - check job progress
- `get_result` - retrieve generated files
