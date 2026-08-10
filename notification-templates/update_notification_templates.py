#!/usr/bin/env python3
"""
Create or update ADOC notification templates.

Default flow:
  1. Find or create the selected template group.
  2. For each source type, load a channel template from disk or copy an
     existing/default template from ADOC.
  3. Create or update that channel template inside the target group.
  4. Optionally wire notification channel groups to the template group.

Examples:
  # Pull existing Slack templates down for editing.
  python3 update_notification_templates.py \
    --adoc-url <account-url> \
    --tenant-id <tenant> \
    --api-key-file <api-key.csv> \
    --template-group-name "<template group>" \
    --channel slack \
    --export-templates \
    --export-dir ./slack_templates

  # Pull existing Email templates down for editing.
  python3 update_notification_templates.py \
    --adoc-url <account-url> \
    --tenant-id <tenant> \
    --api-key-file <api-key.csv> \
    --template-group-name "<template group>" \
    --channel email \
    --export-templates \
    --export-dir ./email_templates

  # Pull Slack templates from every existing template group.
  python3 update_notification_templates.py \
    --adoc-url <account-url> \
    --tenant-id <tenant> \
    --api-key-file <api-key.csv> \
    --channel slack \
    --export-templates \
    --export-all-template-groups \
    --export-dir ./slack_templates

  # Push all JSON templates found in ./slack_templates back to ADOC.
  python3 update_notification_templates.py \
    --adoc-url <account-url> \
    --tenant-id <tenant> \
    --api-key-file <api-key.csv> \
    --template-group-id <template-group-id> \
    --channel slack \
    --template-dir ./slack_templates

  python3 update_notification_templates.py \
    --adoc-url <account-url> \
    --tenant-id <tenant> \
    --api-key-file <api-key.csv> \
    --template-group-id <template-group-id> \
    --channel email \
    --template-dir ./email_templates

  python3 update_notification_templates.py \
    --adoc-url <account-url> \
    --tenant-id <tenant> \
    --api-key-file <api-key.csv> \
    --template-group-id <template-group-id> \
    --wire-channel-groups \
    --namespace-id <namespace-id>
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_SOURCE_TYPES = ["POLICY_EXECUTION", "CRAWLER", "PROFILE"]
DEFAULT_CHANNEL = "slack"
DEFAULT_EXPORT_DIRS = {"slack": "slack_templates", "email": "email_templates"}


@dataclass
class ApiConfig:
    base_url: str
    headers: dict[str, str]
    dry_run: bool = False
    timeout: int = 30
    update_payload_style: str = "contents_only"


def normalize_base_url(base_url: str) -> str:
    if "://" not in base_url:
        base_url = f"https://{base_url}"

    parsed = urlsplit(base_url)
    if parsed.netloc and parsed.path in {"", "/"}:
        return urlunsplit((parsed.scheme, parsed.netloc, "/api", parsed.query, parsed.fragment))
    return base_url


def resolve_adoc_url(value: str | None) -> str:
    url = value or os.environ.get("ADOC_URL")
    if not url:
        raise RuntimeError("--adoc-url or ADOC_URL is required")
    return url


def normalize_channel(value: str) -> str:
    channel = value.strip().lower()
    if channel not in {"slack", "email"}:
        raise argparse.ArgumentTypeError("channel must be either slack or email")
    return channel


def discover_api_key_file() -> Path | None:
    candidates = sorted(
        path
        for pattern in ("*API_Key*.csv", "*api_key*.csv", "*apikey*.csv")
        for path in Path.cwd().glob(pattern)
        if path.is_file()
    )
    unique_candidates = list(dict.fromkeys(candidates))
    if len(unique_candidates) == 1:
        return unique_candidates[0]
    return None


def resolve_api_key_file(value: Path | None) -> Path:
    if value:
        return value
    env_value = os.environ.get("ADOC_API_KEY_FILE")
    if env_value:
        return Path(env_value)
    discovered = discover_api_key_file()
    if discovered:
        print(f"Using discovered API key file: {discovered}")
        return discovered
    raise RuntimeError(
        "--api-key-file or ADOC_API_KEY_FILE is required "
        "unless exactly one *API_Key*.csv file exists in the current directory"
    )


def resolve_template_group_name(value: str | None) -> str | None:
    return value or os.environ.get("ADOC_TEMPLATE_GROUP_NAME")


def require_template_group_identifier(template_group_id: str | None, template_group_name: str | None) -> None:
    if not template_group_id and not template_group_name:
        raise RuntimeError("--template-group-id or --template-group-name/ADOC_TEMPLATE_GROUP_NAME is required")


def parse_key_value(raw: str) -> tuple[str, str] | None:
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return None
    if "=" not in raw:
        return None
    key, value = raw.split("=", 1)
    return key.strip(), value.strip().strip('"').strip("'")


def load_api_key_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    with path.open(newline="") as handle:
        rows = list(csv.reader(handle))

    for row in rows:
        cells = [cell.strip() for cell in row if cell.strip()]
        if not cells:
            continue

        if len(cells) >= 2 and "=" not in cells[0]:
            values[cells[0].strip()] = cells[1].strip().strip('"').strip("'")
            continue

        parsed = parse_key_value(cells[0])
        if parsed:
            key, value = parsed
            values[key] = value

    return values


def env_or_config(config: dict[str, str], *names: str) -> str | None:
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
        if config.get(name):
            return config[name]
    return None


def compact_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def request_json(
    api: ApiConfig,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> Any:
    url = urljoin(normalize_base_url(api.base_url).rstrip("/") + "/", path.lstrip("/"))
    if query:
        filtered_query = {k: v for k, v in query.items() if v is not None}
        if filtered_query:
            url = f"{url}?{urlencode(filtered_query)}"

    data = None
    headers = dict(api.headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    if api.dry_run and method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        print(f"DRY-RUN {method.upper()} {url}")
        if body is not None:
            print(compact_json(body))
        return {"dryRun": True}

    request = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=api.timeout) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method.upper()} {url} failed: HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method.upper()} {url} failed: {exc.reason}") from exc

    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        if payload.lstrip().lower().startswith("<!doctype html") or payload.lstrip().lower().startswith("<html"):
            raise RuntimeError(
                f"{method.upper()} {url} returned HTML instead of JSON. "
                "Check --adoc-url; this environment may need an API gateway prefix."
            )
        return payload


def candidate_lists(data: Any) -> list[list[Any]]:
    if isinstance(data, list):
        return [data]
    if not isinstance(data, dict):
        return []

    lists: list[list[Any]] = []
    for key in (
        "data",
        "content",
        "items",
        "results",
        "records",
        "templateGroups",
        "templateGroupList",
        "templates",
        "templateList",
        "channelGroups",
        "notificationChannelGroups",
    ):
        value = data.get(key)
        if isinstance(value, list):
            lists.append(value)
        elif isinstance(value, dict):
            lists.extend(candidate_lists(value))
    return lists


def as_items(data: Any) -> list[dict[str, Any]]:
    for candidate in candidate_lists(data):
        if all(isinstance(item, dict) for item in candidate):
            return candidate
    return []


def first_value(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if item.get(key) is not None:
            return item[key]
    return None


def group_id(group: dict[str, Any]) -> str | None:
    value = first_value(group, "templateGroupId", "id", "uuid")
    return str(value) if value is not None else None


def group_name(group: dict[str, Any]) -> str | None:
    value = first_value(group, "templateGroupName", "name")
    return str(value) if value is not None else None


def template_id(template: dict[str, Any]) -> str | None:
    value = first_value(template, "templateId", "id", "uuid")
    return str(value) if value is not None else None


def template_channel(template: dict[str, Any]) -> str | None:
    value = first_value(template, "channel", "channelType")
    return str(value) if value is not None else None


def template_source_type(template: dict[str, Any]) -> str | None:
    value = first_value(template, "sourceType", "type")
    return str(value) if value is not None else None


def list_template_groups(api: ApiConfig, name_filter: str | None = None) -> list[dict[str, Any]]:
    response = request_json(
        api,
        "GET",
        "/notifications/api/v1/template-group",
        query={"templateGroupName": name_filter, "size": 100},
    )
    return as_items(response)


def get_template_groups_response(api: ApiConfig, name_filter: str | None = None) -> Any:
    return request_json(
        api,
        "GET",
        "/notifications/api/v1/template-group",
        query={"templateGroupName": name_filter, "size": 100},
    )


def find_template_group(api: ApiConfig, name: str) -> dict[str, Any] | None:
    groups = list_template_groups(api, name)
    for group in groups:
        if group_name(group) == name and group_id(group):
            return group
    return None


def ensure_template_group(api: ApiConfig, name: str, description: str) -> str:
    group = find_template_group(api, name)
    if group:
        gid = group_id(group)
        print(f"Using existing template group '{name}' ({gid})")
        return gid or ""

    body = {"name": name, "description": description}
    response = request_json(api, "POST", "/notifications/api/v1/template-group", body=body)
    created_id = group_id(response or {}) if isinstance(response, dict) else None
    if not created_id and api.dry_run:
        created_id = "DRY_RUN_TEMPLATE_GROUP_ID"
    if not created_id:
        raise RuntimeError(f"Created template group but could not find its ID in response: {response}")
    print(f"Created template group '{name}' ({created_id})")
    return created_id


def resolve_template_group_id(api: ApiConfig, template_group_id: str | None, template_group_name: str) -> str:
    if template_group_id:
        return template_group_id

    group = find_template_group(api, template_group_name)
    if not group or not group_id(group):
        raise RuntimeError(f"Template group '{template_group_name}' was not found.")
    return group_id(group) or ""


def list_group_templates(api: ApiConfig, template_group_id: str) -> list[dict[str, Any]]:
    response = request_json(
        api,
        "GET",
        f"/notifications/api/v1/template-group/{quote(template_group_id)}/template",
    )
    return as_items(response)


def get_group_templates_response(api: ApiConfig, template_group_id: str) -> Any:
    return request_json(
        api,
        "GET",
        f"/notifications/api/v1/template-group/{quote(template_group_id)}/template",
    )


def unwrap_single_item(data: Any) -> Any:
    if isinstance(data, dict):
        for key in ("data", "item", "result", "template"):
            value = data.get(key)
            if isinstance(value, dict):
                return unwrap_single_item(value)
    return data


def get_group_template(api: ApiConfig, template_group_id: str, tid: str) -> dict[str, Any]:
    response = request_json(
        api,
        "GET",
        f"/notifications/api/v1/template-group/{quote(template_group_id)}/template/{quote(tid)}",
    )
    response = unwrap_single_item(response)
    if not isinstance(response, dict):
        raise RuntimeError(f"Template detail response for {tid} was not an object: {response}")
    return response


def extract_template_body(template: dict[str, Any]) -> Any:
    body = first_value(template, "template", "contents", "body", "content")
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return body
    return body


def template_payload(template_body: Any) -> Any:
    if isinstance(template_body, dict) and "content" in template_body:
        return template_body
    if isinstance(template_body, str):
        return {"content": template_body}
    return template_body


def template_content(template_body: Any) -> Any:
    if isinstance(template_body, dict) and "content" in template_body:
        return template_body["content"]
    return template_body


def build_template_body(
    template_body: Any,
    source_type: str,
    existing_template: dict[str, Any] | None,
    template_group_id: str,
    payload_style: str,
) -> dict[str, Any]:
    channel = template_channel(existing_template or {}) or "slack"
    if payload_style == "contents_only":
        return {"contents": template_payload(template_body)}
    if payload_style == "template":
        return {
            "channel": channel,
            "sourceType": source_type,
            "template": template_payload(template_body),
        }
    if payload_style == "template_content":
        return {
            "channel": channel,
            "sourceType": source_type,
            "template": template_content(template_body),
        }
    if payload_style == "contents_content":
        return {
            "channel": channel,
            "sourceType": source_type,
            "contents": template_content(template_body),
        }
    if payload_style == "content":
        return {
            "channel": channel,
            "sourceType": source_type,
            "content": template_content(template_body),
        }
    if payload_style == "body":
        return {
            "channel": channel,
            "sourceType": source_type,
            "body": template_content(template_body),
        }
    if payload_style == "body_object":
        return {
            "channel": channel,
            "sourceType": source_type,
            "body": template_payload(template_body),
        }
    if payload_style == "full":
        body = dict(existing_template or {})
        body.update(
            {
                "channel": channel,
                "sourceType": source_type,
                "templateGroupId": int(template_group_id) if template_group_id.isdigit() else template_group_id,
                "contents": template_payload(template_body),
            }
        )
        return body
    return {
        "channel": channel,
        "sourceType": source_type,
        "contents": template_payload(template_body),
    }


def safe_template_filename(source_type: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_type.strip())
    return f"{name or 'UNKNOWN_SOURCE_TYPE'}.json"


def safe_dir_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return name.strip("._") or "template_group"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def export_channel_templates(api: ApiConfig, template_group_id: str, export_dir: Path, channel: str) -> None:
    templates = list_group_templates(api, template_group_id)
    channel_templates = [
        template
        for template in templates
        if (template_channel(template) or "").lower() == channel
    ]
    if not channel_templates:
        print(f"No {channel.title()} templates found in template group {template_group_id}.")
        return

    manifest: list[dict[str, Any]] = []
    for template in channel_templates:
        tid = template_id(template)
        detailed_template = get_group_template(api, template_group_id, tid) if tid else template
        source_type = template_source_type(template) or "UNKNOWN_SOURCE_TYPE"
        filename = safe_template_filename(source_type)
        output_path = export_dir / filename
        template_body = extract_template_body(detailed_template)
        if template_body is None:
            template_body = extract_template_body(template)
        write_json(output_path, template_body)
        manifest.append(
            {
                "file": filename,
                "templateId": tid,
                "sourceType": source_type,
                "channel": template_channel(template),
                "templateGroupId": template_group_id,
            }
        )
        print(f"Exported {channel.title()} template for {source_type} to {output_path}")

    write_json(export_dir / "_manifest.json", manifest)
    print(f"Exported {len(channel_templates)} {channel.title()} template(s).")


def export_all_channel_templates(api: ApiConfig, export_dir: Path, channel: str) -> None:
    groups = list_template_groups(api)
    if not groups:
        print("No template groups returned by ADOC.")
        return

    exported_groups = 0
    for group in groups:
        gid = group_id(group)
        if not gid:
            continue
        name = group_name(group) or gid
        group_dir = export_dir / f"{safe_dir_name(name)}__{safe_dir_name(gid)}"
        before = len(list(group_dir.glob("*.json"))) if group_dir.exists() else 0
        export_channel_templates(api, gid, group_dir, channel)
        after = len(list(group_dir.glob("*.json"))) if group_dir.exists() else 0
        if after > before:
            exported_groups += 1

    print(
        f"Finished scanning {len(groups)} template group(s); "
        f"exported {channel.title()} templates from {exported_groups}."
    )


def print_template_groups(api: ApiConfig) -> None:
    groups = list_template_groups(api)
    if not groups:
        print("No template groups returned by ADOC.")
        return
    for group in groups:
        print(f"{group_id(group) or '-'}\t{group_name(group) or '-'}")


def print_raw_template_groups(api: ApiConfig, name_filter: str | None) -> None:
    response = get_template_groups_response(api, name_filter)
    print(json.dumps(response, indent=2, sort_keys=True))


def print_raw_group_templates(api: ApiConfig, template_group_id: str) -> None:
    response = get_group_templates_response(api, template_group_id)
    print(json.dumps(response, indent=2, sort_keys=True))


def print_raw_group_template(api: ApiConfig, template_group_id: str, tid: str) -> None:
    response = request_json(
        api,
        "GET",
        f"/notifications/api/v1/template-group/{quote(template_group_id)}/template/{quote(tid)}",
    )
    print(json.dumps(response, indent=2, sort_keys=True))


def find_default_template(
    api: ApiConfig,
    source_type: str,
    target_group_id: str,
    channel: str,
    preferred_group_name: str | None = None,
) -> Any:
    groups = list_template_groups(api, preferred_group_name)
    for group in groups:
        gid = group_id(group)
        if not gid or gid == target_group_id:
            continue
        if preferred_group_name and group_name(group) != preferred_group_name:
            continue

        for template in list_group_templates(api, gid):
            if (template_channel(template) or "").lower() != channel:
                continue
            if (template_source_type(template) or "").lower() != source_type.lower():
                continue
            tid = template_id(template)
            detailed_template = get_group_template(api, gid, tid) if tid else template
            body = extract_template_body(detailed_template)
            if body is None:
                body = extract_template_body(template)
            if body is not None:
                print(f"Copied default {channel.title()} template for {source_type} from group '{group_name(group) or gid}'")
                return body

    raise RuntimeError(
        f"No existing {channel.title()} template found for source type {source_type}. "
        "Provide --template-json or --template-dir, or set --default-template-group-name."
    )


def load_template_from_disk(
    template_json: Path | None,
    template_dir: Path | None,
    source_type: str,
    channel: str,
) -> Any | None:
    if template_dir:
        candidates = [
            template_dir / f"{source_type}.json",
            template_dir / f"{source_type.lower()}.json",
            template_dir / f"{source_type.upper()}.json",
            template_dir / f"{source_type.lower().replace('_', '-')}.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                with candidate.open() as handle:
                    print(f"Loaded {channel.title()} template for {source_type} from {candidate}")
                    return json.load(handle)

    if template_json:
        with template_json.open() as handle:
            print(f"Loaded {channel.title()} template for {source_type} from {template_json}")
            return json.load(handle)

    return None


def upsert_channel_template(
    api: ApiConfig,
    template_group_id: str,
    source_type: str,
    template_body: Any,
    channel: str,
) -> None:
    existing = None
    for template in list_group_templates(api, template_group_id):
        existing_source_type = template_source_type(template) or ""
        if (template_channel(template) or "").lower() == channel and existing_source_type.lower() == source_type.lower():
            tid = template_id(template)
            existing = get_group_template(api, template_group_id, tid) if tid else template
            source_type = existing_source_type
            break

    if existing and template_id(existing):
        tid = template_id(existing)
        body = build_template_body(template_body, source_type, existing, template_group_id, api.update_payload_style)
        request_json(
            api,
            "PUT",
            f"/notifications/api/v1/template-group/{quote(template_group_id)}/template/{quote(tid)}",
            body=body,
        )
        print(f"Updated {channel.title()} template for {source_type} ({tid})")
        return

    body = {
        "channel": channel,
        "sourceType": source_type,
        "contents": template_payload(template_body),
    }
    response = request_json(
        api,
        "POST",
        f"/notifications/api/v1/template-group/{quote(template_group_id)}/template",
        body=body,
    )
    created_id = template_id(response or {}) if isinstance(response, dict) else None
    suffix = f" ({created_id})" if created_id else ""
    print(f"Created {channel.title()} template for {source_type}{suffix}")


def channel_group_id(group: dict[str, Any]) -> str | None:
    value = first_value(group, "channelGroupId", "notificationChannelGroupId", "id", "uuid")
    return str(value) if value is not None else None


def channel_group_name(group: dict[str, Any]) -> str | None:
    value = first_value(group, "channelGroupName", "name")
    return str(value) if value is not None else None


def list_channel_groups(api: ApiConfig, namespace_id: str) -> list[dict[str, Any]]:
    response = request_json(
        api,
        "GET",
        f"/notifications/api/v1/{quote(namespace_id)}/notifications/channels/groups",
    )
    return as_items(response)


def update_channel_groups(
    api: ApiConfig,
    namespace_id: str,
    template_group_id: str,
    selected_ids: set[str],
    name_contains: str | None,
    update_path_mode: str,
) -> None:
    groups = list_channel_groups(api, namespace_id)
    if not groups:
        print("No channel groups returned by ADOC.")
        return

    updated = 0
    for group in groups:
        gid = channel_group_id(group)
        name = channel_group_name(group) or ""
        if not gid:
            continue
        if selected_ids and gid not in selected_ids:
            continue
        if name_contains and name_contains.lower() not in name.lower():
            continue

        body = dict(group)
        body["templateGroupId"] = template_group_id
        path = f"/notifications/api/v1/{quote(namespace_id)}/notifications/channels/groups"
        if update_path_mode == "item":
            path = f"{path}/{quote(gid)}"
        request_json(
            api,
            "PUT",
            path,
            body=body,
        )
        print(f"Wired channel group '{name or gid}' to template group {template_group_id}")
        updated += 1

    if updated == 0:
        print("No channel groups matched the provided filters.")


def discover_template_source_types(template_dir: Path | None) -> list[str]:
    if not template_dir or not template_dir.exists():
        return []

    manifest_path = template_dir / "_manifest.json"
    if manifest_path.exists():
        with manifest_path.open() as handle:
            manifest = json.load(handle)
        if isinstance(manifest, list):
            source_types = []
            for entry in manifest:
                if not isinstance(entry, dict):
                    continue
                source_type = entry.get("sourceType")
                filename = entry.get("file")
                if source_type and filename and (template_dir / filename).exists():
                    source_types.append(str(source_type))
            if source_types:
                return source_types

    source_types: list[str] = []
    for path in sorted(template_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        source_types.append(path.stem.replace("-", "_"))
    return source_types


def parse_source_types(values: list[str] | None, template_dir: Path | None = None) -> list[str]:
    if not values:
        discovered = discover_template_source_types(template_dir)
        if discovered:
            return discovered
        return DEFAULT_SOURCE_TYPES
    source_types: list[str] = []
    for value in values:
        source_types.extend(part.strip() for part in value.split(",") if part.strip())
    return source_types


def build_headers(args: argparse.Namespace, config_values: dict[str, str]) -> dict[str, str]:
    access_key = env_or_config(config_values, "ADOC_ACCESS_KEY", "ACCESS_KEY")
    secret_key = env_or_config(config_values, "ADOC_SECRET_KEY", "SECRET_KEY")
    tenant_id = args.tenant_id or env_or_config(config_values, "ADOC_TENANT_ID", "X_TENANT_ID", "TENANT_ID")
    user_id = args.user_id or env_or_config(config_values, "ADOC_USER_ID", "X_USER_ID", "USER_ID")
    username = args.username or env_or_config(config_values, "ADOC_USERNAME", "X_USERNAME", "USERNAME")

    missing = []
    if not access_key:
        missing.append("ADOC_ACCESS_KEY")
    if not secret_key:
        missing.append("ADOC_SECRET_KEY")
    if not tenant_id:
        missing.append("--tenant-id or ADOC_TENANT_ID")
    if missing:
        raise RuntimeError(f"Missing required credential values: {', '.join(missing)}")

    headers = {
        args.access_key_header: access_key,
        args.secret_key_header: secret_key,
        "X-Tenant-ID": tenant_id,
        "Accept": "application/json",
    }
    if user_id:
        headers[args.user_id_header] = user_id
    if username:
        headers[args.username_header] = username
    return headers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create/update ADOC notification templates in a template group."
    )
    parser.add_argument("--adoc-url", help="ADOC base URL. Can also use ADOC_URL.")
    parser.add_argument(
        "--api-key-file",
        type=Path,
        help=(
            "CSV/key file containing ADOC_ACCESS_KEY and ADOC_SECRET_KEY. "
            "Can also use ADOC_API_KEY_FILE. If omitted, exactly one *API_Key*.csv "
            "file in the current directory will be used."
        ),
    )
    parser.add_argument("--tenant-id", help="Tenant ID for X-Tenant-ID. Can also use ADOC_TENANT_ID.")
    parser.add_argument("--user-id", help="Optional standard user ID header value. Can also use ADOC_USER_ID.")
    parser.add_argument("--username", help="Optional standard username header value. Can also use ADOC_USERNAME.")
    parser.add_argument("--access-key-header", default="accessKey", help="Header name for the access key.")
    parser.add_argument("--secret-key-header", default="secretKey", help="Header name for the secret key.")
    parser.add_argument("--user-id-header", default="X-User-ID", help="Header name for --user-id.")
    parser.add_argument("--username-header", default="X-User-Name", help="Header name for --username.")
    parser.add_argument(
        "--channel",
        type=normalize_channel,
        default=DEFAULT_CHANNEL,
        help="Template channel to export/update: slack or email. Default: slack.",
    )
    parser.add_argument("--template-group-name", help="Template group name. Can also use ADOC_TEMPLATE_GROUP_NAME.")
    parser.add_argument(
        "--template-group-id",
        help="Use this template group ID directly instead of looking it up by --template-group-name.",
    )
    parser.add_argument(
        "--template-group-description",
        default="Custom notification templates managed by automation.",
    )
    parser.add_argument(
        "--source-type",
        action="append",
        help="Source type to upsert. May be repeated or comma-separated. Default: POLICY_EXECUTION,CRAWLER,PROFILE",
    )
    parser.add_argument("--template-json", type=Path, help="Template JSON file to use for all source types.")
    parser.add_argument(
        "--template-dir",
        type=Path,
        help="Directory containing per-source JSON files, such as DATA_QUALITY.json.",
    )
    parser.add_argument(
        "--export-templates",
        action="store_true",
        help="Pull existing templates for --channel into --export-dir, then exit.",
    )
    parser.add_argument(
        "--export-slack-templates",
        action="store_true",
        help="Alias for --channel slack --export-templates.",
    )
    parser.add_argument(
        "--export-email-templates",
        action="store_true",
        help="Alias for --channel email --export-templates.",
    )
    parser.add_argument(
        "--export-all-template-groups",
        action="store_true",
        help="With --export-templates, scan every template group and export templates for --channel.",
    )
    parser.add_argument(
        "--export-dir",
        type=Path,
        help="Directory where exported templates are written. Default: slack_templates or email_templates.",
    )
    parser.add_argument(
        "--list-template-groups",
        action="store_true",
        help="List template group IDs and names, then exit.",
    )
    parser.add_argument(
        "--debug-template-groups-response",
        action="store_true",
        help="Print the raw template-group list response, then exit.",
    )
    parser.add_argument(
        "--debug-group-templates-response",
        action="store_true",
        help="Print the raw templates response for --template-group-id/--template-group-name, then exit.",
    )
    parser.add_argument(
        "--debug-template-response",
        help="Print the raw response for a specific template ID in --template-group-id/--template-group-name, then exit.",
    )
    parser.add_argument(
        "--default-template-group-name",
        help="Optional existing template group to copy default templates from.",
    )
    parser.add_argument(
        "--wire-channel-groups",
        action="store_true",
        help="After upserting templates, set templateGroupId on matching notification channel groups.",
    )
    parser.add_argument("--namespace-id", help="Namespace ID for channel group wiring. Can also use ADOC_NAMESPACE_ID.")
    parser.add_argument(
        "--channel-group-id",
        action="append",
        default=[],
        help="Only wire this channel group ID. May be repeated. If omitted, all returned groups can match.",
    )
    parser.add_argument(
        "--channel-group-name-contains",
        help="Only wire channel groups whose name contains this text.",
    )
    parser.add_argument(
        "--channel-group-update-path",
        choices=["collection", "item"],
        default="collection",
        help="Use the documented collection path or /groups/{id} for channel group PUT. Default: collection.",
    )
    parser.add_argument(
        "--update-payload-style",
        choices=[
            "contents",
            "contents_only",
            "contents_content",
            "content",
            "body",
            "body_object",
            "template",
            "template_content",
            "full",
        ],
        default="contents_only",
        help="Payload shape for template updates. Default: contents_only.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print mutating requests without sending them.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.adoc_url = resolve_adoc_url(args.adoc_url)
    args.api_key_file = resolve_api_key_file(args.api_key_file)
    args.template_group_name = resolve_template_group_name(args.template_group_name)
    if args.export_email_templates:
        args.channel = "email"
        args.export_templates = True
    if args.export_slack_templates:
        args.channel = "slack"
        args.export_templates = True
    if args.export_dir is None:
        args.export_dir = Path(DEFAULT_EXPORT_DIRS[args.channel])

    config_values = load_api_key_file(args.api_key_file)
    headers = build_headers(args, config_values)
    api = ApiConfig(args.adoc_url, headers, args.dry_run, args.timeout, args.update_payload_style)

    if args.debug_template_groups_response:
        print_raw_template_groups(api, args.template_group_name)
        return 0

    if args.debug_group_templates_response:
        require_template_group_identifier(args.template_group_id, args.template_group_name)
        template_group_id = resolve_template_group_id(api, args.template_group_id, args.template_group_name)
        print_raw_group_templates(api, template_group_id)
        return 0

    if args.debug_template_response:
        require_template_group_identifier(args.template_group_id, args.template_group_name)
        template_group_id = resolve_template_group_id(api, args.template_group_id, args.template_group_name)
        print_raw_group_template(api, template_group_id, args.debug_template_response)
        return 0

    if args.list_template_groups:
        print_template_groups(api)
        return 0

    if args.export_templates:
        if args.export_all_template_groups:
            export_all_channel_templates(api, args.export_dir, args.channel)
        else:
            require_template_group_identifier(args.template_group_id, args.template_group_name)
            template_group_id = resolve_template_group_id(api, args.template_group_id, args.template_group_name)
            export_channel_templates(api, template_group_id, args.export_dir, args.channel)
        print("Done.")
        return 0

    source_types = parse_source_types(args.source_type, args.template_dir)
    if args.template_group_id:
        template_group_id = args.template_group_id
    else:
        if not args.template_group_name:
            raise RuntimeError("--template-group-id or --template-group-name/ADOC_TEMPLATE_GROUP_NAME is required")
        template_group_id = ensure_template_group(
            api,
            args.template_group_name,
            args.template_group_description,
        )

    for source_type in source_types:
        template_body = load_template_from_disk(args.template_json, args.template_dir, source_type, args.channel)
        if template_body is None:
            template_body = find_default_template(
                api,
                source_type,
                template_group_id,
                args.channel,
                preferred_group_name=args.default_template_group_name,
            )
        upsert_channel_template(api, template_group_id, source_type, template_body, args.channel)

    if args.wire_channel_groups:
        namespace_id = args.namespace_id or os.environ.get("ADOC_NAMESPACE_ID")
        if not namespace_id:
            raise RuntimeError("--namespace-id or ADOC_NAMESPACE_ID is required with --wire-channel-groups")
        update_channel_groups(
            api,
            namespace_id,
            template_group_id,
            set(args.channel_group_id),
            args.channel_group_name_contains,
            args.channel_group_update_path,
        )

    print("Done.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
