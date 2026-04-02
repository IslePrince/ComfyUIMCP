import copy
import json
import logging
import random
from pathlib import Path
from typing import Any

import yaml

from models import CapabilitySummary, ParameterDef

logger = logging.getLogger(__name__)


class Capability:
    def __init__(self, name: str, manifest: dict, workflow: dict):
        self.name = name
        self.manifest = manifest
        self.workflow = workflow

    @property
    def display_name(self) -> str:
        return self.manifest.get("display_name", self.name)

    @property
    def description(self) -> str:
        return self.manifest.get("description", "")

    @property
    def category(self) -> str:
        return self.manifest.get("category", "general")

    @property
    def parameters(self) -> list[ParameterDef]:
        return [ParameterDef(**p) for p in self.manifest.get("parameters", [])]

    @property
    def node_mappings(self) -> dict[str, list[str]]:
        return self.manifest.get("node_mappings", {})

    def to_summary(self) -> CapabilitySummary:
        return CapabilitySummary(
            name=self.name,
            display_name=self.display_name,
            description=self.description,
            category=self.category,
            parameters=self.parameters,
        )


class Catalog:
    def __init__(self, workflows_dir: str = "/app/workflows"):
        self.workflows_dir = Path(workflows_dir)
        self.capabilities: dict[str, Capability] = {}
        self._load_all()

    def _load_all(self):
        if not self.workflows_dir.exists():
            logger.warning(f"Workflows directory not found: {self.workflows_dir}")
            return

        for subdir in sorted(self.workflows_dir.iterdir()):
            if not subdir.is_dir():
                continue
            manifest_path = subdir / "manifest.yaml"
            workflow_path = subdir / "workflow.json"
            if not manifest_path.exists() or not workflow_path.exists():
                logger.warning(f"Skipping {subdir.name}: missing manifest.yaml or workflow.json")
                continue

            try:
                with open(manifest_path) as f:
                    manifest = yaml.safe_load(f)
                with open(workflow_path) as f:
                    workflow = json.load(f)
                name = manifest.get("name", subdir.name)
                self.capabilities[name] = Capability(name, manifest, workflow)
                logger.info(f"Loaded capability: {name}")
            except Exception as e:
                logger.error(f"Failed to load {subdir.name}: {e}")

    def list_capabilities(self) -> list[CapabilitySummary]:
        return [cap.to_summary() for cap in self.capabilities.values()]

    def build_prompt(self, capability_name: str, params: dict[str, Any]) -> dict:
        """Build a ComfyUI prompt by patching the workflow template with user params."""
        if capability_name not in self.capabilities:
            available = ", ".join(self.capabilities.keys())
            raise ValueError(f"Unknown capability '{capability_name}'. Available: {available}")

        cap = self.capabilities[capability_name]
        workflow = copy.deepcopy(cap.workflow)

        # Validate required params
        for param_def in cap.parameters:
            if param_def.required and param_def.name not in params:
                raise ValueError(f"Missing required parameter: {param_def.name}")

        # Apply params via node_mappings
        for param_name, value in params.items():
            if param_name not in cap.node_mappings:
                continue
            # Convert -1 seed to random value (ComfyUI requires seed >= 0)
            if param_name == "seed" and value == -1:
                value = random.randint(0, 2**63)
            paths = cap.node_mappings[param_name]
            for path in paths:
                self._set_nested(workflow, path, value)

        # Apply defaults for unset params
        for param_def in cap.parameters:
            if param_def.name not in params and param_def.default is not None:
                if param_def.name in cap.node_mappings:
                    for path in cap.node_mappings[param_def.name]:
                        self._set_nested(workflow, path, param_def.default)

        return workflow

    @staticmethod
    def _set_nested(obj: dict, path: str, value: Any):
        """Set a value in a nested dict using dot-separated path like '6.inputs.text'."""
        keys = path.split(".")
        for key in keys[:-1]:
            obj = obj[key]
        obj[keys[-1]] = value
