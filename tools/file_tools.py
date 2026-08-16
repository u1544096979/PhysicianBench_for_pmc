"""
File utility tools: write_file.

Plain functions (no class wrappers) for the tool-calling agent.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any



def write_file(file_path: str, content: str, mode: str = "w") -> dict[str, Any]:
    """Write text content to a file.

    Args:
        file_path: Absolute path to write to.
        content: Text content to write.
        mode: 'w' to overwrite (default), 'a' to append.

    Returns:
        dict with status and path.
    """
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content) if mode == "w" else p.open("a").write(content)
    return {"status": "ok", "path": str(p), "bytes_written": len(content)}


def make_workspace_write_file(workspace_root: Path) -> Callable[..., dict[str, Any]]:
    """Bind ``write_file`` to one workspace and reject path escapes."""
    resolved_root = Path(workspace_root).resolve()

    def restricted_write_file(file_path: str, content: str, mode: str = "w") -> dict[str, Any]:
        candidate = Path(file_path)
        if not candidate.is_absolute():
            raise ValueError("file_path must be absolute and inside the workspace")
        resolved_candidate = candidate.resolve()
        try:
            resolved_candidate.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("file_path must resolve inside the workspace") from exc
        return write_file(str(resolved_candidate), content, mode)

    return restricted_write_file
