"""Pull an event log out of 1C:Enterprise over OData.

Why a connector at all: 1C cannot push. Every other source system here posts
its own events, but an accounting database has no hooks to hang that on, so we
fetch on a schedule instead.

What this can and cannot reconstruct
------------------------------------
The documents in this base carry no link to each other - `ДокументОснование`
and `Сделка` are empty on every posted record we sampled. A single sale
therefore cannot be traced from invoice to payment: the data to do it is not
there, and guessing the links from amounts and dates would produce a confident
picture of a process nobody runs.

So a *case* here is a counterparty within one month, not one transaction. That
answers "how does business with this client flow, and where does it stall" -
which is the question the data can honestly support.

Times are also unreliable: 1C stamps bulk-posted documents with the same
minute, so everything is treated at day resolution.

    docker compose exec process-mining python -m app.connectors.onec --days 60
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Iterator

# Document -> the activity name that appears on the process map. Order matters
# only for reading this list; the map is built from timestamps.
DOCUMENTS: dict[str, str] = {
    "РеализацияТоваровУслуг": "Отгрузка",
    "СчетФактураВыданный": "Счёт-фактура",
    "ЭСФ": "ЭСФ",
    "ПлатежноеПоручениеВходящее": "Оплата (банк)",
    "ПриходныйКассовыйОрдер": "Оплата (касса)",
}

# 1C answers with a bounded page regardless of what we ask for; paging is by
# $skip until a short page comes back.
PAGE = 1000
CASE_TYPE = "sales_1c"


class Client:
    def __init__(self, base: str, user: str, password: str, timeout: int = 120) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._auth = base64.b64encode(f"{user}:{password}".encode()).decode()

    def get(self, entity: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        query = "&".join(
            f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items()
        )
        url = f"{self.base}/{urllib.parse.quote(entity)}?{query}"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Basic {self._auth}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8")).get("value", [])
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            raise RuntimeError(f"1C answered HTTP {exc.code} for {entity}: {body}") from exc

    def pages(self, entity: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        skip = 0
        while True:
            batch = self.get(entity, {**params, "$top": PAGE, "$skip": skip})
            if not batch:
                return
            yield from batch
            if len(batch) < PAGE:
                return
            skip += len(batch)


def load_env() -> dict[str, str]:
    """Environment first, then the stack's .env - so this runs both inside the
    container and straight from a shell on the host."""
    env = dict(os.environ)
    for candidate in ("/srv/.env", os.path.expanduser("~/Process-Mining/.env"), ".env"):
        if not os.path.exists(candidate):
            continue
        with open(candidate, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env.setdefault(key.strip(), value.strip())
        break
    return env


def counterparty_names(client: Client) -> dict[str, str]:
    """GUID -> name, so the map reads as customers rather than hex."""
    names: dict[str, str] = {}
    try:
        for row in client.pages(
            "Catalog_Контрагенты",
            {"$format": "json", "$select": "Ref_Key,Description"},
        ):
            if row.get("Ref_Key"):
                names[row["Ref_Key"]] = (row.get("Description") or "").strip()
    except RuntimeError as exc:
        print(f"  ! could not read the counterparty catalog: {exc}", file=sys.stderr)
    return names


def collect(client: Client, days: int) -> tuple[list[dict[str, Any]], Counter]:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
    # Anything dated ahead of today is an unposted draft or a typo; letting it
    # through would end cases in the future and skew every duration.
    until = datetime.now().strftime("%Y-%m-%dT23:59:59")
    names = counterparty_names(client)
    print(f"  counterparties in catalogue: {len(names)}")

    events: list[dict[str, Any]] = []
    stats: Counter = Counter()

    for document, activity in DOCUMENTS.items():
        params = {
            "$format": "json",
            "$filter": (
                f"Posted eq true and Date ge datetime'{since}' and Date le datetime'{until}'"
            ),
            "$orderby": "Date",
        }
        try:
            rows = list(client.pages(f"Document_{document}", params))
        except RuntimeError as exc:
            print(f"  ! {document}: {exc}", file=sys.stderr)
            continue

        kept = 0
        for row in rows:
            when = (row.get("Date") or "")[:19]
            party = row.get("Контрагент_Key") or row.get("ДоговорКонтрагента_Key")
            if not when or not party:
                continue
            # Case = one client, one month. See the module docstring for why a
            # per-transaction case is not reconstructable from this data.
            case_id = f"{names.get(party, party[:8])} · {when[:7]}"
            events.append(
                {
                    "event_id": str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"1c:{document}:{row.get('Ref_Key')}")
                    ),
                    "case_id": case_id,
                    "case_type": CASE_TYPE,
                    "activity": activity,
                    "timestamp": when + "+05:00",
                    "resource": names.get(party, ""),
                    "order_number": (row.get("Number") or "").strip(),
                    "metadata": json.dumps(
                        {"document": document, "counterparty": names.get(party, "")},
                        ensure_ascii=False,
                    ),
                }
            )
            kept += 1
        stats[activity] = kept
        print(f"  {activity:<18} {kept:>6} событий  (получено {len(rows)})")

    return events, stats


COLUMNS = [
    "event_id", "case_id", "case_type", "activity", "timestamp", "user_id", "user_name",
    "resource", "product_id", "product_name", "batch_number", "order_number",
    "from_stage", "to_stage", "status", "quantity", "unit", "problem_type", "metadata",
]


def to_csv(events: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for event in sorted(events, key=lambda e: e["timestamp"]):
        writer.writerow({column: event.get(column, "") for column in COLUMNS})
    return buffer.getvalue().encode("utf-8")


def push(payload: bytes, url: str, token: str, source: str) -> dict[str, Any]:
    export_id = str(uuid.uuid4())
    boundary = "----pm1c" + uuid.uuid4().hex
    fields = {
        "export_id": export_id,
        "source": source,
        "schema_version": "1.0",
        "checksum": hashlib.sha256(payload).hexdigest(),
        "events_count": str(payload.decode("utf-8").count("\n") - 1),
    }
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(f"{value}\r\n".encode())
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(
        b'Content-Disposition: form-data; name="file"; filename="onec.csv"\r\n'
        b"Content-Type: text/csv\r\n\r\n"
    )
    chunks.append(payload)
    chunks.append(f"\r\n--{boundary}--\r\n".encode())

    request = urllib.request.Request(
        url,
        data=b"".join(chunks),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": export_id,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="1C OData -> process mining event log")
    parser.add_argument("--days", type=int, default=60, help="how far back to read")
    parser.add_argument("--source", default="goldsapa_1c")
    parser.add_argument("--import-url", default="http://localhost:8000/api/event-logs/import/")
    parser.add_argument("--dry-run", action="store_true", help="build the CSV, do not send it")
    args = parser.parse_args()

    env = load_env()
    missing = [k for k in ("ONEC_URL", "ONEC_USER", "ONEC_PASSWORD") if not env.get(k)]
    if missing:
        print("missing in environment: " + ", ".join(missing), file=sys.stderr)
        return 2

    client = Client(env["ONEC_URL"], env["ONEC_USER"], env["ONEC_PASSWORD"])
    print(f"reading the last {args.days} days from 1C")
    events, _ = collect(client, args.days)
    if not events:
        print("nothing to import")
        return 1

    cases = len({e["case_id"] for e in events})
    print(f"\n  total: {len(events)} events in {cases} cases")

    payload = to_csv(events)
    if args.dry_run:
        sys.stdout.buffer.write(payload[:1500])
        print(f"\n  (dry run, {len(payload)} bytes)")
        return 0

    token = (env.get("PM_API_KEYS") or "").split(",")[0].strip()
    if not token:
        print("PM_API_KEYS is not set - cannot authenticate to the importer", file=sys.stderr)
        return 2
    answer = push(payload, args.import_url, token, args.source)
    print(f"  imported: {json.dumps(answer, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
