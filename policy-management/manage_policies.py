#!/usr/bin/env python3
"""
List and update ADOC policies.

Examples:
  # List every policy visible to the account.
  python3 manage_policies.py list \
    --adoc-url <account-url> \
    --api-key-file <api-key.csv> \
    --policy-type all

  # List only Data Quality policies.
  python3 manage_policies.py list \
    --adoc-url <account-url> \
    --api-key-file <api-key.csv> \
    --policy-type data-quality

  # Update one Data Quality policy by name.
  python3 manage_policies.py update \
    --adoc-url <account-url> \
    --api-key-file <api-key.csv> \
    --policy-type data-quality \
    --policy-name Customer_DQ_Policy \
    --payload-file policy_update.json \
    --dry-run

  # Update a group of Data Freshness policies by type and name filter.
  python3 manage_policies.py update-matching \
    --adoc-url <account-url> \
    --api-key-file <api-key.csv> \
    --policy-type data-freshness \
    --name-contains critical \
    --set-enabled false \
    --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 100


@dataclass(frozen=True)
class PolicyTypeConfig:
    label: str
    rule_type: str
    path_name: str
    supports_by_name: bool = False
    supports_by_asset: bool = False


POLICY_TYPES = {
    "data-quality": PolicyTypeConfig("Data Quality", "DATA_QUALITY", "data-quality", True),
    "dq": PolicyTypeConfig("Data Quality", "DATA_QUALITY", "data-quality", True),
    "data-freshness": PolicyTypeConfig("Data Freshness", "DATA_CADENCE", "data-cadence", False, True),
    "freshness": PolicyTypeConfig("Data Freshness", "DATA_CADENCE", "data-cadence", False, True),
    "data-cadence": PolicyTypeConfig("Data Freshness", "DATA_CADENCE", "data-cadence", False, True),
    "reconciliation": PolicyTypeConfig("Reconciliation", "RECONCILIATION", "reconciliation"),
    "equality": PolicyTypeConfig("Reconciliation", "EQUALITY", "reconciliation"),
    "data-drift": PolicyTypeConfig("Data Drift", "DATA_DRIFT", "data-drift"),
    "schema-drift": PolicyTypeConfig("Schema Drift", "SCHEMA_DRIFT", "schema-drift"),
    "data-anomaly": PolicyTypeConfig("Data Anomaly", "DATA_ANOMALY", "data-anomaly"),
    "auto-anomaly": PolicyTypeConfig("Auto Anomaly", "AUTO_ANOMALY", "auto-anomaly"),
    "profile-anomaly": PolicyTypeConfig("Profile Anomaly", "PROFILE_ANOMALY", "profile-anomaly"),
}


@dataclass
class ApiConfig:
    base_url: str
    headers: dict[str, str]
    dry_run: bool = False
    timeout: int = 30


def normalize_base_url(base_url: str, api_prefix: str | None = None) -> str:
    if "://" not in base_url:
        base_url = f"https://{base_url}"

    parsed = urlsplit(base_url)
    if api_prefix:
        prefix = "/" + api_prefix.strip("/")
        return urlunsplit((parsed.scheme, parsed.netloc, prefix, parsed.query, parsed.fragment))
    return base_url.rstrip("/")


def resolve_adoc_url(value: str | None) -> str:
    url = value or os.environ.get("ADOC_URL")
    if not url:
        raise RuntimeError("--adoc-url or ADOC_URL is required")
    return url


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


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on", "enabled", "active"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off", "disabled", "inactive"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected a boolean value, got {value!r}")


def compact_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def request_json(
    api: ApiConfig,
    method: str,
    path: str,
    body: dict[str, Any] | list[Any] | None = None,
    query: dict[str, Any] | None = None,
) -> Any:
    url = urljoin(api.base_url.rstrip("/") + "/", path.lstrip("/"))
    if query:
        filtered_query = {k: v for k, v in query.items() if v is not None}
        if filtered_query:
            url = f"{url}?{urlencode(filtered_query, doseq=True)}"

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
                "Check --adoc-url and try --api-prefix api if this account routes APIs under /api."
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
        "rules",
        "policies",
        "policyDefinitions",
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


def unwrap_item(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict):
        for key in ("data", "item", "result", "policy", "ruleDefinition"):
            value = data.get(key)
            if isinstance(value, dict):
                return unwrap_item(value)
        return data
    return None


def first_value(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if item.get(key) is not None:
            return item[key]
    return None


def get_rule(item: dict[str, Any]) -> dict[str, Any]:
    rule = item.get("rule")
    return rule if isinstance(rule, dict) else item


def policy_id(item: dict[str, Any]) -> str | None:
    rule = get_rule(item)
    value = first_value(
        item,
        "policyId",
        "ruleId",
        "id",
        "policy_id",
        "rule_id",
    )
    if value is None:
        value = first_value(rule, "id", "policyId", "ruleId", "policy_id", "rule_id")
    return str(value) if value is not None else None


def policy_name(item: dict[str, Any]) -> str | None:
    rule = get_rule(item)
    value = first_value(item, "policyName", "ruleName", "name", "policy_name", "rule_name")
    if value is None:
        value = first_value(rule, "name", "policyName", "ruleName", "policy_name", "rule_name")
    return str(value) if value is not None else None


def policy_type(item: dict[str, Any]) -> str | None:
    rule = get_rule(item)
    value = first_value(item, "policyType", "ruleType", "type", "policy_type", "rule_type")
    if value is None:
        value = first_value(rule, "type", "policyType", "ruleType", "policy_type", "rule_type")
    return str(value) if value is not None else None


def policy_enabled(item: dict[str, Any]) -> Any:
    rule = get_rule(item)
    value = first_value(item, "enabled", "enable", "active")
    if value is None:
        value = first_value(rule, "enabled", "enable", "active")
    return value


def policy_status(item: dict[str, Any]) -> Any:
    rule = get_rule(item)
    value = first_value(item, "status", "state", "ruleStatus")
    if value is None:
        value = first_value(rule, "status", "state", "ruleStatus")
    return value


def policy_scheduled(item: dict[str, Any]) -> Any:
    rule = get_rule(item)
    value = first_value(item, "scheduled")
    if value is None:
        value = first_value(rule, "scheduled")
    return value


def policy_asset_id(item: dict[str, Any]) -> Any:
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    backing_asset = details.get("backingAsset") if isinstance(details.get("backingAsset"), dict) else {}
    rule = get_rule(item)
    value = first_value(
        item,
        "assetId",
        "asset_id",
        "backingAssetId",
        "tableAssetId",
    )
    if value is None:
        value = first_value(rule, "assetId", "asset_id", "backingAssetId", "tableAssetId")
    if value is None and isinstance(backing_asset, dict):
        value = first_value(backing_asset, "tableAssetId", "assetId", "id")
    return value


def format_bool(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "t", "yes", "y", "on", "enabled", "active"}:
            return True
        if normalized in {"0", "false", "f", "no", "n", "off", "disabled", "inactive"}:
            return False
    return None


def normalize_policy_type(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    if normalized == "all":
        return "all"
    if normalized not in POLICY_TYPES:
        choices = ", ".join(sorted({"all", *POLICY_TYPES.keys()}))
        raise argparse.ArgumentTypeError(f"Unknown policy type {value!r}. Choices: {choices}")
    return normalized


def policy_config(policy_type_value: str) -> PolicyTypeConfig:
    normalized = normalize_policy_type(policy_type_value)
    if normalized == "all":
        raise RuntimeError("A specific --policy-type is required for this command")
    return POLICY_TYPES[normalized]


def load_json_file(path: Path) -> Any:
    with path.open() as handle:
        return json.load(handle)


def parse_set_values(values: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise RuntimeError(f"--set expects KEY=VALUE, got {value!r}")
        key, raw = value.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        assign_nested(result, key.split("."), parsed)
    return result


def assign_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    current = target
    for part in path[:-1]:
        existing = current.get(part)
        if not isinstance(existing, dict):
            existing = {}
            current[part] = existing
        current = existing
    current[path[-1]] = value


def deep_merge(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = dict(base)
        for key, value in overlay.items():
            merged[key] = deep_merge(merged.get(key), value)
        return merged
    return overlay


def build_update_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if args.payload_file:
        loaded = load_json_file(args.payload_file)
        if not isinstance(loaded, dict):
            raise RuntimeError("--payload-file must contain a JSON object")
        payload = loaded

    generated_rule: dict[str, Any] = {}
    if args.set_enabled is not None:
        generated_rule["enabled"] = args.set_enabled
    if args.set_scheduled is not None:
        generated_rule["scheduled"] = args.set_scheduled
    if args.schedule:
        generated_rule["schedule"] = args.schedule
        generated_rule.setdefault("scheduled", True)
    if args.status:
        generated_rule["status"] = args.status

    if generated_rule:
        payload = deep_merge(payload, {"rule": generated_rule})

    set_values = parse_set_values(args.set or [])
    if set_values:
        payload = deep_merge(payload, set_values)

    if not payload:
        raise RuntimeError("Provide --payload-file, --set, --set-enabled, --set-scheduled, --schedule, or --status")
    return payload


def build_headers(args: argparse.Namespace, config_values: dict[str, str]) -> dict[str, str]:
    access_key = env_or_config(config_values, "ADOC_ACCESS_KEY", "ACCESS_KEY")
    secret_key = env_or_config(config_values, "ADOC_SECRET_KEY", "SECRET_KEY")
    tenant_id = args.tenant_id or env_or_config(config_values, "ADOC_TENANT_ID", "X_TENANT_ID", "TENANT_ID")
    user_id = args.user_id or env_or_config(config_values, "ADOC_USER_ID", "X_USER_ID", "USER_ID")
    username = args.username or env_or_config(config_values, "ADOC_USERNAME", "X_USERNAME", "USERNAME")
    bearer_token = args.bearer_token or env_or_config(config_values, "ADOC_BEARER_TOKEN", "BEARER_TOKEN", "TOKEN")

    missing = []
    if not access_key:
        missing.append("ADOC_ACCESS_KEY")
    if not secret_key:
        missing.append("ADOC_SECRET_KEY")
    if missing:
        raise RuntimeError(f"Missing required credential values: {', '.join(missing)}")

    headers = {
        args.access_key_header: access_key,
        args.secret_key_header: secret_key,
        "Accept": "application/json",
    }
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    if user_id:
        headers[args.user_id_header] = user_id
    if username:
        headers[args.username_header] = username
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    return headers


def list_policies(api: ApiConfig, args: argparse.Namespace) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    config = POLICY_TYPES.get(args.policy_type)
    page = args.page

    for _ in range(args.max_pages):
        query: dict[str, Any] = {
            "page": page,
            "size": args.size,
            "withLatestExecution": str(args.with_latest_execution).lower(),
        }
        if config:
            query["ruleType"] = config.rule_type
        if args.asset_id:
            query["assetIds"] = ",".join(args.asset_id)
        if args.only_active is not None:
            query["onlyActive"] = str(args.only_active).lower()
        if args.name_contains:
            query["name"] = args.name_contains
        if args.sort_by:
            query["sortBy"] = args.sort_by

        response = request_json(api, "GET", "/catalog-server/api/rules", query=query)
        page_items = as_items(response)
        items.extend(page_items)

        if args.no_all_pages:
            break
        if not page_items or len(page_items) < args.size:
            break
        if isinstance(response, dict):
            total_pages = first_value(response, "totalPages", "pages")
            data = response.get("data")
            if total_pages is None and isinstance(data, dict):
                total_pages = first_value(data, "totalPages", "pages")
            if total_pages is not None and page + 1 >= int(total_pages):
                break
        page += 1

    return apply_local_filters(items, args)


def apply_local_filters(items: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    filtered = items
    if args.name_contains:
        needle = args.name_contains.lower()
        filtered = [item for item in filtered if needle in (policy_name(item) or "").lower()]
    if args.enabled is not None:
        filtered = [item for item in filtered if bool_value(policy_enabled(item)) is args.enabled]
    if args.scheduled is not None:
        filtered = [item for item in filtered if bool_value(policy_scheduled(item)) is args.scheduled]
    if args.policy_id:
        selected_ids = set(args.policy_id)
        filtered = [item for item in filtered if (policy_id(item) or "") in selected_ids]
    if args.policy_name:
        selected_names = {name.lower() for name in args.policy_name}
        filtered = [item for item in filtered if (policy_name(item) or "").lower() in selected_names]
    return filtered


def print_policies(items: list[dict[str, Any]], output: str) -> None:
    if output == "json":
        print(json.dumps(items, indent=2, sort_keys=True))
        return
    if output == "ids":
        for item in items:
            pid = policy_id(item)
            if pid:
                print(pid)
        return

    print("id\tname\ttype\tstatus\tenabled\tscheduled\tasset_id")
    for item in items:
        print(
            "\t".join(
                [
                    policy_id(item) or "-",
                    policy_name(item) or "-",
                    policy_type(item) or "-",
                    str(policy_status(item) or "-"),
                    format_bool(policy_enabled(item)),
                    format_bool(policy_scheduled(item)),
                    str(policy_asset_id(item) or "-"),
                ]
            )
        )


def detail_path(config: PolicyTypeConfig, pid: str) -> str:
    return f"/catalog-server/api/rules/{config.path_name}/{quote(str(pid))}"


def get_policy_by_id(api: ApiConfig, config: PolicyTypeConfig, pid: str) -> dict[str, Any]:
    response = request_json(api, "GET", detail_path(config, pid))
    item = unwrap_item(response)
    if not item:
        raise RuntimeError(f"Policy {pid} response was not an object: {response}")
    return item


def get_policy_by_asset(api: ApiConfig, config: PolicyTypeConfig, asset_id: str) -> dict[str, Any]:
    if not config.supports_by_asset:
        raise RuntimeError(f"{config.label} does not support lookup by asset in this script")
    response = request_json(api, "GET", f"/catalog-server/api/rules/{config.path_name}/byAsset/{quote(asset_id)}")
    item = unwrap_item(response)
    if not item:
        raise RuntimeError(f"Asset {asset_id} response was not an object: {response}")
    return item


def update_policy_by_id(api: ApiConfig, config: PolicyTypeConfig, pid: str, payload: dict[str, Any]) -> None:
    request_json(api, "PUT", detail_path(config, pid), body=payload)
    print(f"Updated {config.label} policy {pid}")


def update_policy_by_name(api: ApiConfig, config: PolicyTypeConfig, name: str, payload: dict[str, Any]) -> None:
    if not config.supports_by_name:
        raise RuntimeError(f"{config.label} policies cannot be updated by name with the published API")
    request_json(
        api,
        "PUT",
        f"/catalog-server/api/rules/{config.path_name}/byName/{quote(name)}",
        body=payload,
    )
    print(f"Updated {config.label} policy '{name}'")


def resolve_update_targets(api: ApiConfig, config: PolicyTypeConfig, args: argparse.Namespace) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for pid in args.policy_id or []:
        targets.append({"id": pid})
    for asset_id in args.asset_id or []:
        item = get_policy_by_asset(api, config, asset_id)
        pid = policy_id(item)
        if not pid:
            raise RuntimeError(f"Could not find policy ID in policy response for asset {asset_id}")
        targets.append({"id": pid, "assetId": asset_id})
    for name in args.policy_name or []:
        if config.supports_by_name:
            targets.append({"name": name})
        else:
            raise RuntimeError(f"{config.label} policies require --policy-id or --asset-id for updates")
    if not targets:
        raise RuntimeError("Provide --policy-id, --policy-name, or --asset-id")
    return targets


def maybe_merge_payload(
    api: ApiConfig,
    config: PolicyTypeConfig,
    target: dict[str, str],
    payload: dict[str, Any],
    merge_current: bool,
) -> dict[str, Any]:
    if not merge_current:
        return payload
    pid = target.get("id")
    if not pid:
        raise RuntimeError("--merge-current requires update targets with IDs")
    current = get_policy_by_id(api, config, pid)
    return deep_merge(current, payload)


def update_targets(
    api: ApiConfig,
    config: PolicyTypeConfig,
    targets: list[dict[str, str]],
    payload: dict[str, Any],
    merge_current: bool,
) -> None:
    for target in targets:
        body = maybe_merge_payload(api, config, target, payload, merge_current)
        if target.get("id"):
            update_policy_by_id(api, config, target["id"], body)
        elif target.get("name"):
            update_policy_by_name(api, config, target["name"], body)


def export_details(api: ApiConfig, config: PolicyTypeConfig, items: list[dict[str, Any]], export_dir: Path) -> None:
    export_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for item in items:
        pid = policy_id(item)
        if not pid:
            continue
        detail = get_policy_by_id(api, config, pid)
        name = policy_name(detail) or policy_name(item) or pid
        filename = safe_filename(f"{name}__{pid}.json")
        output_path = export_dir / filename
        with output_path.open("w") as handle:
            json.dump(detail, handle, indent=2, sort_keys=True)
            handle.write("\n")
        manifest.append({"file": filename, "id": pid, "name": name, "type": policy_type(detail) or config.rule_type})
        print(f"Exported {name} ({pid}) to {output_path}")
    with (export_dir / "_manifest.json").open("w") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")


def safe_filename(value: str) -> str:
    allowed = []
    for char in value:
        if char.isalnum() or char in {"-", "_", "."}:
            allowed.append(char)
        else:
            allowed.append("_")
    name = "".join(allowed).strip("._")
    return name or "policy.json"


def command_list(api: ApiConfig, args: argparse.Namespace) -> int:
    items = list_policies(api, args)
    if args.export_dir:
        if args.policy_type == "all":
            raise RuntimeError("--export-dir requires a specific --policy-type")
        export_details(api, policy_config(args.policy_type), items, args.export_dir)
    print_policies(items, args.output)
    print(f"Found {len(items)} policy/policies.", file=sys.stderr)
    return 0


def command_get(api: ApiConfig, args: argparse.Namespace) -> int:
    config = policy_config(args.policy_type)
    results: list[dict[str, Any]] = []
    for pid in args.policy_id or []:
        results.append(get_policy_by_id(api, config, pid))
    for asset_id in args.asset_id or []:
        results.append(get_policy_by_asset(api, config, asset_id))
    if not results:
        raise RuntimeError("Provide --policy-id or --asset-id")
    if args.output == "json":
        print(json.dumps(results[0] if len(results) == 1 else results, indent=2, sort_keys=True))
    else:
        print_policies(results, args.output)
    return 0


def command_update(api: ApiConfig, args: argparse.Namespace) -> int:
    config = policy_config(args.policy_type)
    payload = build_update_payload(args)
    targets = resolve_update_targets(api, config, args)
    update_targets(api, config, targets, payload, args.merge_current)
    print("Done.")
    return 0


def command_update_matching(api: ApiConfig, args: argparse.Namespace) -> int:
    if args.policy_type == "all":
        raise RuntimeError("update-matching requires a specific --policy-type")
    config = policy_config(args.policy_type)
    payload = build_update_payload(args)
    items = list_policies(api, args)
    targets = [{"id": pid} for item in items if (pid := policy_id(item))]

    if not targets:
        print("No policies matched the provided filters.")
        return 0
    if not args.dry_run and not args.yes:
        raise RuntimeError(
            f"Refusing to update {len(targets)} policies without --yes. "
            "Run with --dry-run first to review requests."
        )

    print(f"Matched {len(targets)} {config.label} policy/policies.")
    update_targets(api, config, targets, payload, args.merge_current)
    print("Done.")
    return 0


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--adoc-url", help="ADOC base URL. Can also use ADOC_URL.")
    parser.add_argument(
        "--api-prefix",
        help=(
            "Optional API gateway prefix, for example 'api'. "
            "Use this if the account expects /api/catalog-server instead of /catalog-server."
        ),
    )
    parser.add_argument(
        "--api-key-file",
        type=Path,
        help=(
            "CSV/key file containing ADOC_ACCESS_KEY and ADOC_SECRET_KEY. "
            "Can also use ADOC_API_KEY_FILE. If omitted, exactly one *API_Key*.csv "
            "file in the current directory will be used."
        ),
    )
    parser.add_argument("--tenant-id", help="Optional tenant ID for X-Tenant-ID. Can also use ADOC_TENANT_ID.")
    parser.add_argument("--user-id", help="Optional standard user ID header value. Can also use ADOC_USER_ID.")
    parser.add_argument("--username", help="Optional standard username header value. Can also use ADOC_USERNAME.")
    parser.add_argument("--bearer-token", help="Optional bearer token. Can also use ADOC_BEARER_TOKEN or TOKEN.")
    parser.add_argument("--access-key-header", default="accessKey", help="Header name for the access key.")
    parser.add_argument("--secret-key-header", default="secretKey", help="Header name for the secret key.")
    parser.add_argument("--user-id-header", default="X-User-ID", help="Header name for --user-id.")
    parser.add_argument("--username-header", default="X-User-Name", help="Header name for --username.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")
    parser.add_argument("--dry-run", action="store_true", help="Print mutating requests without sending them.")


def add_filter_args(parser: argparse.ArgumentParser, *, include_targets: bool = True) -> None:
    parser.add_argument(
        "--policy-type",
        type=normalize_policy_type,
        default="all",
        help=(
            "Policy type filter. Common values: all, data-quality, data-freshness, "
            "data-drift, schema-drift, reconciliation."
        ),
    )
    parser.add_argument("--name-contains", help="Only include policies whose name contains this text.")
    parser.add_argument("--asset-id", action="append", default=[], help="Filter by asset ID. May be repeated.")
    parser.add_argument("--enabled", type=parse_bool, help="Only include policies with this enabled value.")
    parser.add_argument("--scheduled", type=parse_bool, help="Only include policies with this scheduled value.")
    parser.add_argument("--only-active", type=parse_bool, help="Pass onlyActive to the listing endpoint.")
    if include_targets:
        parser.add_argument("--policy-id", action="append", default=[], help="Policy ID. May be repeated.")
        parser.add_argument("--policy-name", action="append", default=[], help="Policy name. May be repeated.")


def add_listing_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--page", type=int, default=0, help="Zero-based page to start from. Default: 0.")
    parser.add_argument("--size", type=int, default=DEFAULT_PAGE_SIZE, help="Page size. Default: 100.")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES, help="Maximum pages to scan.")
    parser.add_argument("--no-all-pages", action="store_true", help="Only request the starting page.")
    parser.add_argument("--sort-by", help="Sort expression, for example name:ASC.")
    parser.add_argument(
        "--with-latest-execution",
        type=parse_bool,
        default=True,
        help="Ask list endpoint to include latest execution metadata. Default: true.",
    )


def add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", choices=["table", "json", "ids"], default="table", help="Output format.")


def add_update_payload_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--payload-file", type=Path, help="JSON object to send as the update body.")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        help="Set a JSON value by dotted path, for example --set rule.description='new text'. May be repeated.",
    )
    parser.add_argument("--set-enabled", type=parse_bool, help="Set rule.enabled.")
    parser.add_argument("--set-scheduled", type=parse_bool, help="Set rule.scheduled.")
    parser.add_argument("--schedule", help="Set rule.schedule and force rule.scheduled=true.")
    parser.add_argument("--status", help="Set rule.status.")
    parser.add_argument(
        "--merge-current",
        action="store_true",
        help="GET each policy first and deep-merge the update payload before PUT.",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List and update ADOC policies.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List policies.")
    add_common_args(list_parser)
    add_filter_args(list_parser)
    add_listing_args(list_parser)
    add_output_args(list_parser)
    list_parser.add_argument("--export-dir", type=Path, help="Export matching policy details to this directory.")

    get_parser = subparsers.add_parser("get", help="Get policy detail by ID or freshness asset ID.")
    add_common_args(get_parser)
    get_parser.add_argument(
        "--policy-type",
        type=normalize_policy_type,
        required=True,
        help="Specific policy type, such as data-quality or data-freshness.",
    )
    get_parser.add_argument("--policy-id", action="append", default=[], help="Policy ID. May be repeated.")
    get_parser.add_argument(
        "--asset-id",
        action="append",
        default=[],
        help="Asset ID. Currently useful for data-freshness lookups. May be repeated.",
    )
    add_output_args(get_parser)

    update_parser = subparsers.add_parser("update", help="Update specific policies by ID, name, or asset.")
    add_common_args(update_parser)
    update_parser.add_argument(
        "--policy-type",
        type=normalize_policy_type,
        required=True,
        help="Specific policy type, such as data-quality or data-freshness.",
    )
    update_parser.add_argument("--policy-id", action="append", default=[], help="Policy ID. May be repeated.")
    update_parser.add_argument(
        "--policy-name",
        action="append",
        default=[],
        help="Policy name. Supported by the published Data Quality by-name API.",
    )
    update_parser.add_argument(
        "--asset-id",
        action="append",
        default=[],
        help="Freshness asset ID to resolve via /data-cadence/byAsset/{id}. May be repeated.",
    )
    add_update_payload_args(update_parser)

    matching_parser = subparsers.add_parser("update-matching", help="Update every policy matching list filters.")
    add_common_args(matching_parser)
    add_filter_args(matching_parser)
    add_listing_args(matching_parser)
    add_update_payload_args(matching_parser)
    matching_parser.add_argument("--yes", action="store_true", help="Required for non-dry-run group updates.")

    return parser.parse_args()


def build_api(args: argparse.Namespace) -> ApiConfig:
    args.adoc_url = resolve_adoc_url(args.adoc_url)
    args.api_key_file = resolve_api_key_file(args.api_key_file)
    config_values = load_api_key_file(args.api_key_file)
    headers = build_headers(args, config_values)
    base_url = normalize_base_url(args.adoc_url, args.api_prefix)
    return ApiConfig(base_url, headers, args.dry_run, args.timeout)


def main() -> int:
    args = parse_args()
    api = build_api(args)

    if args.command == "list":
        return command_list(api, args)
    if args.command == "get":
        return command_get(api, args)
    if args.command == "update":
        return command_update(api, args)
    if args.command == "update-matching":
        return command_update_matching(api, args)
    raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
