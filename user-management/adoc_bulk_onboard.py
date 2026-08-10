#!/usr/bin/env python3
"""Bulk-invite users to an ADOC tenant and assign them to groups from a CSV file.

Authentication (confirmed working): "accessKey" / "secretKey" HTTP headers.

Invite request body (confirmed working against a live tenant):
    POST /admin/api/users/invite-users
    {"userDetails": [{"email": ...}, ...], "groups": [<group id>, ...], "sendEmail": bool}
"groups" is a Keycloak group ID (UUID), not a group name, and applies to every email in
that call -- so this script fetches GET /admin/api/groups once to resolve the CSV's group
names to IDs, and groups users needing the same set of groups into shared invite calls
(users needing different group combinations get separate calls).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import re
import shlex
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable, Iterator


DEFAULT_BATCH_SIZE = 100


class ADOCError(RuntimeError):
    pass


class ADOCClient:
    def __init__(
        self,
        base_url: str,
        access_key: str,
        secret_key: str,
        *,
        access_key_header: str = "accessKey",
        secret_key_header: str = "secretKey",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            access_key_header: access_key,
            secret_key_header: secret_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "adoc-bulk-onboard/1",
        }

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise ADOCError(f"ADOC API returned HTTP {exc.code} for {method} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ADOCError(f"Could not reach {url}: {exc.reason}") from exc
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.decode(errors="replace")


def read_env_file(path: pathlib.Path) -> dict[str, str]:
    """Read a small, shell-compatible subset of dotenv syntax without executing it."""
    path = path.expanduser()
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ADOCError(f"Could not read environment file {path}: {exc}") from exc
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ADOCError(f"Invalid .env entry at {path}:{line_number}")
        raw_value = raw_value.strip()
        if raw_value.startswith(("'", '"')):
            try:
                parsed = shlex.split(raw_value, comments=True, posix=True)
            except ValueError as exc:
                raise ADOCError(f"Invalid quoted value at {path}:{line_number}: {exc}") from exc
            if len(parsed) != 1:
                raise ADOCError(f"Invalid quoted value at {path}:{line_number}")
            value = parsed[0]
        else:
            value = re.split(r"\s+#", raw_value, maxsplit=1)[0].strip()
        values[key] = value
    return values


def read_csv_rows(path: pathlib.Path) -> list[tuple[str, str]]:
    """Read (email, group) pairs from a CSV file where each row is an email followed
    by one or more group names: "email,group1,group2,...". Rows can have a different
    number of groups. A header row (first cell without "@") is skipped if present.

    Blank lines are skipped. Exact duplicate (email, group) pairs are dropped, preserving
    first-seen order, so an accidentally repeated group on the same row is not double-sent.
    """
    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    try:
        with path.expanduser().open(newline="", encoding="utf-8-sig") as handle:
            for line_number, record in enumerate(csv.reader(handle), 1):
                cells = [cell.strip() for cell in record if cell.strip()]
                if not cells:
                    continue
                email, *groups = cells
                if "@" not in email:
                    if line_number == 1:
                        continue  # header row
                    raise ADOCError(f"{path}:{line_number}: {email!r} does not look like an email")
                if not groups:
                    raise ADOCError(f"{path}:{line_number}: at least one group is required for {email}")
                for group in groups:
                    pair = (email, group)
                    if pair in seen:
                        continue
                    seen.add(pair)
                    rows.append(pair)
    except OSError as exc:
        raise ADOCError(f"Could not read {path}: {exc}") from exc
    if not rows:
        raise ADOCError(f"{path} contains no usable rows")
    return rows


def summarize_by_email(rows: list[tuple[str, str]]) -> dict[str, list[str]]:
    groups_by_email: dict[str, list[str]] = {}
    for email, group in rows:
        groups_by_email.setdefault(email, []).append(group)
    return groups_by_email


def limit_rows_by_user(rows: list[tuple[str, str]], limit: int) -> list[tuple[str, str]]:
    """Keep only the first `limit` distinct users, with all of each user's groups intact.

    Slicing the flat (email, group) pair list directly would cut a user off mid-row,
    dropping some of their groups -- e.g. --limit 1 on a row with 2 groups would keep
    only the first group instead of testing that user's full, real invitation.
    """
    if limit < 1:
        raise ADOCError("--limit must be at least 1")
    selected_emails: list[str] = []
    for email, _ in rows:
        if email not in selected_emails:
            selected_emails.append(email)
    selected = set(selected_emails[:limit])
    return [pair for pair in rows if pair[0] in selected]


def group_by_groupset(rows: list[tuple[str, str]]) -> dict[tuple[str, ...], list[str]]:
    """Map each distinct, order-independent set of groups to the emails that need it.

    The invite-users API applies its "groups" array to every email in the same call
    (confirmed via the documented request shape: {"emails": [...], "groups": [...],
    "sendEmail": ...}), so users needing different group combinations cannot share a
    call -- each unique combination of groups gets its own batch(es).
    """
    emails_by_groupset: dict[tuple[str, ...], list[str]] = {}
    for email, groups in summarize_by_email(rows).items():
        key = tuple(sorted(set(groups)))
        emails_by_groupset.setdefault(key, []).append(email)
    return emails_by_groupset


def chunked(items: list[str], size: int) -> Iterator[list[str]]:
    if size < 1:
        raise ADOCError("--batch-size must be at least 1")
    for start in range(0, len(items), size):
        yield items[start : start + size]


def extract_list(payload: Any, candidate_keys: tuple[str, ...]) -> list[Any]:
    """Pull a list out of an API response whose exact wrapper shape isn't documented.

    Tries known candidate keys first, then falls back to a single list-valued key so
    this keeps working if the real wrapper key turns out to be something else.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in candidate_keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        list_values = [value for value in payload.values() if isinstance(value, list)]
        if len(list_values) == 1:
            return list_values[0]
    raise ADOCError(
        "Could not find a list in the response; top-level keys: "
        f"{sorted(payload) if isinstance(payload, dict) else type(payload).__name__}"
    )


def fetch_group_ids(client: ADOCClient) -> dict[str, str]:
    """Fetch GET /admin/api/groups and map each group name to its Keycloak group ID.

    invite-users' "groups" field takes Keycloak group IDs, not names (confirmed by a
    live 404 from Keycloak.getUserGroupById when a group name was sent), so CSV group
    names must be resolved to IDs via this endpoint before building the invite payload.
    """
    payload = client.request("GET", "/admin/api/groups")
    groups = extract_list(payload, ("groups", "result", "data"))
    group_ids: dict[str, str] = {}
    for group in groups:
        name = group.get("name")
        group_id = group.get("id")
        if name and group_id:
            group_ids[name] = str(group_id)
    return group_ids


def resolve_group_ids(names: tuple[str, ...], group_ids: dict[str, str]) -> list[str]:
    missing = [name for name in names if name not in group_ids]
    if missing:
        raise ADOCError(
            f"Unknown group name(s): {', '.join(missing)}. "
            f"Available: {', '.join(sorted(group_ids))}"
        )
    return [group_ids[name] for name in names]


def invite_batch(client: ADOCClient, emails: list[str], groups: tuple[str, ...], send_email: bool) -> Any:
    """Call invite-users with the confirmed-required "userDetails" wrapper key and
    "groups" as a top-level sibling (per the documented "emails"+"groups" shape),
    rather than nesting groups inside each userDetails entry -- both prior attempts at
    that nesting round-tripped with an empty "groups" array on the created user.
    """
    return client.request(
        "POST",
        "/admin/api/users/invite-users",
        body={
            "userDetails": [{"email": email} for email in emails],
            "groups": list(groups),
            "sendEmail": send_email,
        },
    )


def print_preview(rows: list[tuple[str, str]], batch_size: int, send_email: bool) -> None:
    groups_by_email = summarize_by_email(rows)
    emails_by_groupset = group_by_groupset(rows)
    total_batches = sum(
        (len(emails) + batch_size - 1) // batch_size for emails in emails_by_groupset.values()
    )
    print(
        f"Planned: {len(groups_by_email)} user(s), {len(emails_by_groupset)} distinct group "
        f"combination(s), {total_batches} batch(es) of up to {batch_size} email(s); "
        f"sendEmail={send_email}"
    )
    for groups, emails in emails_by_groupset.items():
        print(f"  groups=[{', '.join(groups)}]: {', '.join(sorted(emails))}")
    print("Preview only; re-run with --apply to call the ADOC API.")


def run_apply(
    client: ADOCClient, rows: list[tuple[str, str]], batch_size: int, send_email: bool
) -> int:
    group_ids = fetch_group_ids(client)
    failures = 0
    for groups, emails in group_by_groupset(rows).items():
        try:
            resolved_ids = resolve_group_ids(groups, group_ids)
        except ADOCError as exc:
            failures += 1
            print(f"  FAILED: {exc}", file=sys.stderr)
            continue
        for batch in chunked(emails, batch_size):
            print(f"Batch (groups=[{', '.join(groups)}]): {len(batch)} email(s) -> {', '.join(batch)}")
            try:
                response = invite_batch(client, batch, resolved_ids, send_email)
            except ADOCError as exc:
                failures += 1
                print(f"  FAILED: {exc}", file=sys.stderr)
                continue
            print(f"  Response: {json.dumps(response) if response is not None else '(empty)'}")
    return failures


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument(
        "csv_file",
        type=pathlib.Path,
        help="CSV file; each row is an email followed by one or more group names",
    )
    root.add_argument("--url", help="ADOC tenant base URL (overrides environment and .env)")
    root.add_argument(
        "--env-file",
        type=pathlib.Path,
        default=pathlib.Path(".env"),
        help="Credentials file (default: .env; process environment takes precedence)",
    )
    root.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Invitations per API call (default: {DEFAULT_BATCH_SIZE})",
    )
    root.add_argument(
        "--limit", type=int, help="Only process the first N users, keeping each user's full group list (for testing)"
    )
    send_email = root.add_mutually_exclusive_group()
    send_email.add_argument(
        "--send-email", dest="send_email", action="store_true", default=True,
        help="Have ADOC email invited users (default)",
    )
    send_email.add_argument(
        "--no-send-email", dest="send_email", action="store_false",
        help="Suppress invitation emails (useful for a first test run)",
    )
    root.add_argument("--apply", action="store_true", help="Call the ADOC API (default is preview only)")
    root.add_argument(
        "--access-key-header",
        default="accessKey",
        help="HTTP header name for the access key (default: accessKey)",
    )
    root.add_argument(
        "--secret-key-header",
        default="secretKey",
        help="HTTP header name for the secret key (default: secretKey)",
    )
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        rows = read_csv_rows(args.csv_file)
        if args.limit is not None:
            rows = limit_rows_by_user(rows, args.limit)

        if not args.apply:
            print_preview(rows, args.batch_size, args.send_email)
            return 0

        env_file_values = read_env_file(args.env_file)
        base_url = args.url or os.environ.get("ADOC_URL") or env_file_values.get("ADOC_URL")
        if not base_url:
            raise ADOCError("Set ADOC_URL or pass --url")
        access_key = os.environ.get("ADOC_ACCESS_KEY") or env_file_values.get("ADOC_ACCESS_KEY")
        secret_key = os.environ.get("ADOC_SECRET_KEY") or env_file_values.get("ADOC_SECRET_KEY")
        if not access_key or not secret_key:
            raise ADOCError("Set ADOC_ACCESS_KEY and ADOC_SECRET_KEY; keys are never stored on disk by this script")

        client = ADOCClient(
            base_url,
            access_key,
            secret_key,
            access_key_header=args.access_key_header,
            secret_key_header=args.secret_key_header,
        )
        failures = run_apply(client, rows, args.batch_size, args.send_email)
        if failures:
            print(f"Completed with {failures} failed batch(es).", file=sys.stderr)
            return 1
        print("All batches submitted successfully.")
        return 0
    except ADOCError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
