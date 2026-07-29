"""Graphviz rendering with the Windows/permission pitfalls already solved.

The prototype hit ``PermissionError: [Errno 13]`` because it rendered into the
project directory. We always render into a private temp dir, read the bytes
back and delete it. Rendering also runs with a timeout - a pathological model
must never wedge a worker.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.errors import RenderingError
from app.logging_config import get_logger

log = get_logger(__name__)

CONTENT_TYPES = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "dot": "text/vnd.graphviz",
}


def graphviz_available() -> bool:
    return shutil.which("dot") is not None


def ensure_graphviz() -> None:
    if not graphviz_available():
        raise RenderingError(
            "Graphviz binary 'dot' is not on PATH. Install graphviz or request format=json."
        )


def render(gviz: Any, output_format: str = "svg", timeout: int = 60) -> tuple[str, str]:
    """Renders a graphviz object.

    Returns ``(payload, content_type)`` where payload is SVG/DOT text or a
    base64-encoded PNG.
    """
    output_format = output_format.lower()
    if output_format not in CONTENT_TYPES:
        raise RenderingError(f"Unsupported render format '{output_format}'")

    if output_format == "dot":
        return str(gviz.source), CONTENT_TYPES["dot"]

    ensure_graphviz()
    gviz.format = output_format

    workdir = Path(tempfile.mkdtemp(prefix="pm_render_"))
    try:
        source_path = workdir / "graph.gv"
        source_path.write_text(str(gviz.source), encoding="utf-8")
        target_path = workdir / f"graph.{output_format}"
        try:
            subprocess.run(
                ["dot", f"-T{output_format}", str(source_path), "-o", str(target_path)],
                check=True,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RenderingError(f"Graph rendering timed out after {timeout}s") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="replace")[:500] if exc.stderr else ""
            raise RenderingError(f"Graphviz failed: {stderr}") from exc

        data = target_path.read_bytes()
        if output_format == "svg":
            return data.decode("utf-8", errors="replace"), CONTENT_TYPES["svg"]
        return base64.b64encode(data).decode("ascii"), CONTENT_TYPES["png"]
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
