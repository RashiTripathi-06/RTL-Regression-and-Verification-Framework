from __future__ import annotations
import abc
import importlib
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from .reference_verifier import ParsedVector
from .models import ModuleInfo


class ReferenceProvider(abc.ABC):
    """
    Abstract Base Class for custom project-specific reference generators and decoders.
    Researchers only implement this when their expected vectors cannot be statically
    expressed as standard CSV, JSON, or MEM files.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique identifier for this reference provider."""
        pass

    @abc.abstractmethod
    def generate_vectors(
        self,
        dut: ModuleInfo,
        config: Dict[str, Any],
        workspace_root: Path
    ) -> List[ParsedVector]:
        """
        Dynamically computes or decodes expected input/output vectors for the DUT.
        Returns a list of ParsedVector objects.
        """
        pass


class ExtensionRegistry:
    """
    Safe, dynamic loader for optional user extensions.
    Guarantees:
    - Never imports or executes extensions unless explicitly declared in configuration.
    - If an extension fails to load or is missing, gracefully reports failure
      without causing unrelated verification tasks to crash.
    """

    @staticmethod
    def load_provider(provider_spec: str, workspace_root: Path) -> Optional[ReferenceProvider]:
        """
        Loads a provider from a string spec: "module.submodule:ClassName" or "path/to/file.py:ClassName".
        """
        if not provider_spec or ":" not in provider_spec:
            return None
        mod_part, cls_part = provider_spec.split(":", 1)
        mod_part = mod_part.strip()
        cls_part = cls_part.strip()

        try:
            # Check if mod_part is a file path
            if mod_part.endswith(".py") or "/" in mod_part or "\\" in mod_part:
                p = (workspace_root / mod_part).resolve()
                if not p.exists():
                    return None
                spec = importlib.util.spec_from_file_location("custom_extension_provider", str(p))
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    cls_obj = getattr(mod, cls_part)
                    return cls_obj()
            else:
                mod = importlib.import_module(mod_part)
                cls_obj = getattr(mod, cls_part)
                return cls_obj()
        except Exception:
            return None
