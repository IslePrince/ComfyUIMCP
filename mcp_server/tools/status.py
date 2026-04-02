import base64
import os

from fastmcp import FastMCP

from models import JobStatus


def register_status_tools(mcp: FastMCP, catalog, client):
    @mcp.tool()
    async def get_status(prompt_id: str) -> dict:
        """Check the progress and status of a generation job.

        Args:
            prompt_id: The prompt_id returned from a generate call
        """
        # Check in-memory job tracker first
        if prompt_id in client.jobs:
            job = client.jobs[prompt_id]
            result = JobStatus(
                prompt_id=prompt_id,
                status=job["status"],
                progress=job["progress"],
                result_files=job["result_files"],
                error=job["error"],
            )
            return result.model_dump()

        # Fallback: check ComfyUI history
        try:
            history = await client.get_history(prompt_id)
            if not history:
                return {"prompt_id": prompt_id, "status": "unknown", "message": "Job not found"}

            outputs = history.get("outputs", {})
            files = []
            for node_outputs in outputs.values():
                for key in ("images", "gifs", "videos"):
                    for item in node_outputs.get(key, []):
                        files.append(item)

            return JobStatus(
                prompt_id=prompt_id,
                status="completed" if files else "running",
                progress=1.0 if files else 0.5,
                result_files=files,
            ).model_dump()
        except Exception as e:
            return {"prompt_id": prompt_id, "status": "error", "message": str(e)}

    @mcp.tool()
    async def get_result(prompt_id: str, format: str = "path") -> dict:
        """Retrieve the generated files from a completed job.

        Args:
            prompt_id: The prompt_id from a generate call
            format: 'path' returns file paths in the output directory,
                    'base64' returns the file data encoded as base64
        """
        # Get job info
        job = client.jobs.get(prompt_id)
        if not job:
            # Try history
            history = await client.get_history(prompt_id)
            if not history:
                return {"error": f"Job {prompt_id} not found"}
            outputs = history.get("outputs", {})
            files = []
            for node_outputs in outputs.values():
                for key in ("images", "gifs", "videos"):
                    for item in node_outputs.get(key, []):
                        files.append(item)
        else:
            if job["status"] != "completed":
                return {
                    "error": f"Job not yet completed. Status: {job['status']}, Progress: {job['progress']:.0%}",
                }
            files = job["result_files"]

        if not files:
            return {"error": "No output files found for this job"}

        output_dir = os.environ.get("OUTPUT_DIR", "/app/output")
        results = []

        for file_info in files:
            filename = file_info.get("filename", "")
            subfolder = file_info.get("subfolder", "")
            file_type = file_info.get("type", "output")

            if format == "base64":
                try:
                    data = await client.get_image_bytes(filename, subfolder, file_type)
                    results.append({
                        "filename": filename,
                        "data": base64.b64encode(data).decode("utf-8"),
                        "size_bytes": len(data),
                    })
                except Exception as e:
                    results.append({"filename": filename, "error": str(e)})
            else:
                # Return the path in the output directory
                path = os.path.join(output_dir, subfolder, filename) if subfolder else os.path.join(output_dir, filename)
                # Also provide the host-side path hint
                host_path = os.path.join("output", subfolder, filename) if subfolder else os.path.join("output", filename)
                results.append({
                    "filename": filename,
                    "container_path": path,
                    "host_path": host_path,
                    "subfolder": subfolder,
                })

        return {
            "prompt_id": prompt_id,
            "files": results,
            "count": len(results),
        }
