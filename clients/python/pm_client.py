"""Minimal, dependency-light Python client + smoke test.

Copy this file into any sibling project - it is the whole integration.

    from pm_client import ProcessMiningClient

    pm = ProcessMiningClient("http://process-mining:8000", api_key="...")
    result = pm.mine_file("orders.csv", algorithm="dfg_performance", output_format="svg")
    open("map.svg", "w").write(result["result"]["image"])

Run it directly for an end-to-end smoke test:

    python pm_client.py --base-url http://localhost:8000 --api-key dev --file sample.csv
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


class ProcessMiningError(RuntimeError):
    def __init__(self, status: int, body: Any) -> None:
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


class ProcessMiningClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout: int = 300) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    # ---- plumbing ------------------------------------------------------
    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        headers.update(extra or {})
        return headers

    def _request(self, method: str, path: str, *, data: bytes | None = None,
                 headers: dict[str, str] | None = None, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        request = urllib.request.Request(url, data=data, method=method, headers=self._headers(headers))
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    return json.loads(payload or b"null")
                return payload
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = raw.decode("utf-8", errors="replace")
            raise ProcessMiningError(exc.code, body) from exc

    def _post_json(self, path: str, payload: dict[str, Any], **kwargs: Any) -> Any:
        return self._request(
            "POST",
            path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            **kwargs,
        )

    @staticmethod
    def _multipart(fields: dict[str, str], file_path: Path | None,
                   file_field: str = "file") -> tuple[bytes, str]:
        boundary = "----pm" + uuid.uuid4().hex
        chunks: list[bytes] = []
        for name, value in fields.items():
            if value is None:
                continue
            chunks.append(f"--{boundary}\r\n".encode())
            chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            chunks.append(f"{value}\r\n".encode())
        if file_path is not None:
            mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            chunks.append(f"--{boundary}\r\n".encode())
            chunks.append(
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_path.name}"\r\n'.encode()
            )
            chunks.append(f"Content-Type: {mime}\r\n\r\n".encode())
            chunks.append(file_path.read_bytes())
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    # ---- API -----------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health/ready")

    def profiles(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/mapping-profiles")

    def mine_file(self, path: str | Path, *, algorithm: str = "dfg_frequency",
                  output_format: str = "json", mapping_profile: str | None = None,
                  columns: dict[str, Any] | None = None, filters: dict[str, Any] | None = None,
                  noise_threshold: float = 0.0, include_statistics: bool = True) -> dict[str, Any]:
        """Stateless: one call in, full answer out."""
        body, content_type = self._multipart(
            {
                "algorithm": algorithm,
                "format": output_format,
                "mapping_profile": mapping_profile,
                "columns": json.dumps(columns) if columns else None,
                "filters": json.dumps(filters) if filters else None,
                "noise_threshold": str(noise_threshold),
                "include_statistics": str(include_statistics).lower(),
            },
            Path(path),
        )
        return self._request("POST", "/api/v1/mine", data=body,
                             headers={"Content-Type": content_type})

    def upload_log(self, path: str | Path, *, name: str | None = None, tenant: str | None = None,
                   mapping_profile: str | None = None,
                   columns: dict[str, Any] | None = None) -> dict[str, Any]:
        body, content_type = self._multipart(
            {
                "name": name,
                "tenant": tenant,
                "mapping_profile": mapping_profile,
                "columns": json.dumps(columns) if columns else None,
            },
            Path(path),
        )
        return self._request("POST", "/api/v1/logs/upload", data=body,
                             headers={"Content-Type": content_type})

    def create_log(self, name: str, events: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        return self._post_json("/api/v1/logs", {"name": name, "events": events, **kwargs})

    def append_events(self, log_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        return self._post_json(f"/api/v1/logs/{log_id}/events", {"events": events})

    def discover(self, log_id: str, **payload: Any) -> dict[str, Any]:
        return self._post_json(f"/api/v1/logs/{log_id}/discover", payload)

    def process_map_svg(self, log_id: str, algorithm: str = "dfg_frequency") -> str:
        data = self._request("GET", f"/api/v1/logs/{log_id}/map",
                             params={"algorithm": algorithm, "format": "svg"})
        return data.decode("utf-8") if isinstance(data, bytes) else str(data)

    def statistics(self, log_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/logs/{log_id}/statistics")

    def variants(self, log_id: str, limit: int = 20) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/logs/{log_id}/variants", params={"limit": limit})

    def bottlenecks(self, log_id: str, limit: int = 10) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/logs/{log_id}/bottlenecks", params={"limit": limit})

    def conformance(self, log_id: str, **payload: Any) -> dict[str, Any]:
        return self._post_json(f"/api/v1/logs/{log_id}/conformance", payload)

    def delete_log(self, log_id: str) -> None:
        self._request("DELETE", f"/api/v1/logs/{log_id}")


def _smoke(base_url: str, api_key: str | None, file_path: str) -> None:
    client = ProcessMiningClient(base_url, api_key)
    print("health      :", client.health()["status"])
    print("profiles    :", [p["id"] for p in client.profiles()])

    uploaded = client.upload_log(file_path, name="smoke test", mapping_profile="bakery")
    log_id = uploaded["log"]["log_id"]
    print("log         :", log_id, uploaded["log"]["events"], "events")

    stats = client.statistics(log_id)
    print("cases       :", stats["cases"], "| median cycle:",
          round(stats["throughput_seconds"]["median"] / 60, 1), "min")

    top = client.bottlenecks(log_id, limit=3)["bottlenecks"]
    for item in top:
        print(f"bottleneck  : {item['source']} -> {item['target']} "
              f"{round(item['mean_duration_seconds'] / 60, 1)} min avg")

    svg = client.process_map_svg(log_id)
    Path("process_map.svg").write_text(svg, encoding="utf-8")
    print("svg         : process_map.svg", len(svg), "bytes")

    client.delete_log(log_id)
    print("cleanup     : ok")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process Mining Service smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--file", default="examples/sample_log.csv")
    args = parser.parse_args()
    _smoke(args.base_url, args.api_key, args.file)
