# ADOC Notification Template Automation

This repository contains a Python script for exporting and updating ADOC notification templates. It is mainly used when a team needs to make controlled changes to Slack or Email notification templates across ADOC policy source types, then push those changes back to a customer/account environment.

The main script is:

```bash
update_notification_templates.py
```

There is also a policy-management helper:

```bash
manage_policies.py
```

It lists policies across an account and can update one policy or a filtered group of policies, including Data Quality and Data Freshness/Data Cadence policies.

It works with ADOC notification template groups. A template group is the container, and each template inside the group is tied to a notification channel, such as Slack or Email, and a `sourceType`, such as `DATA_QUALITY`, `CRAWLER`, or `PROFILE`.

## Table Of Contents

Repo contents:

- [README.md](README.md): this guide.
- [update_notification_templates.py](update_notification_templates.py): export, create, update, and wire ADOC notification templates.
- [manage_policies.py](manage_policies.py): list and update ADOC policies.
- [dags/adoc_aruba_connectivity_smoke.py](dags/adoc_aruba_connectivity_smoke.py): Airflow DAG for Aruba ADOC connectivity validation.
- [slack_templates/](slack_templates/): Slack notification template payloads by source type.
- [email_templates/](email_templates/): Email notification template payloads by source type.

Guide sections:

- [What The Script Does](#what-the-script-does)
- [Requirements](#requirements)
- [Credentials](#credentials)
- [Common Inputs](#common-inputs)
- [List Policies](#list-policies)
- [Update One Policy](#update-one-policy)
- [Update A Group Of Policies](#update-a-group-of-policies)
- [List Template Groups](#list-template-groups)
- [Export Slack Templates](#export-slack-templates)
- [Export Email Templates](#export-email-templates)
- [Export From All Template Groups](#export-from-all-template-groups)
- [Edit Templates](#edit-templates)
- [Dry Run Before Updating](#dry-run-before-updating)
- [Push All Templates](#push-all-templates)
- [Push One Specific Template](#push-one-specific-template)
- [Create Or Reuse A Template Group By Name](#create-or-reuse-a-template-group-by-name)
- [Wire Notification Channel Groups](#wire-notification-channel-groups)
- [Troubleshooting](#troubleshooting)
- [Airflow ADOC Connectivity Smoke DAG](#airflow-adoc-connectivity-smoke-dag)
- [Repository Safety](#repository-safety)

## What The Script Does

- Lists ADOC notification template groups.
- Exports existing Slack or Email templates from a template group into local JSON files.
- Creates or updates Slack or Email templates in a selected template group.
- Supports updating one template or all templates in a local template directory.
- Optionally wires notification channel groups to a template group.

The safest normal workflow is:

1. Export templates from ADOC.
2. Edit the exported JSON files locally.
3. Run a dry run to preview updates.
4. Push the templates back to ADOC.

## Requirements

- Python 3.10 or newer.
- Network access to the target ADOC URL.
- An ADOC API key file with access key and secret key values.
- The tenant ID for the ADOC account.
- The target template group ID or template group name.

No third-party Python packages are required. The script uses only the Python standard library.

## Credentials

Do not commit API keys, environment files, or customer-specific secrets to Git.

The script accepts a CSV/key file containing:

```text
ADOC_ACCESS_KEY,<access-key>
ADOC_SECRET_KEY,<secret-key>
```

It also accepts `KEY=value` style files:

```bash
ADOC_ACCESS_KEY="<access-key>"
ADOC_SECRET_KEY="<secret-key>"
ADOC_TENANT_ID="<tenant-id>"
```

You can pass the key file explicitly:

```bash
python3 update_notification_templates.py \
  --api-key-file ./customer_API_Key.csv \
  ...
```

If `--api-key-file` is omitted, the script will automatically use the file in the current directory when exactly one file matches one of these patterns:

- `*API_Key*.csv`
- `*api_key*.csv`
- `*apikey*.csv`

## Common Inputs

Most commands need these values:

```bash
--adoc-url <account-url>
--tenant-id <tenant-id>
--api-key-file <api-key.csv>
--template-group-id <template-group-id>
```

You can use a hostname without `https://`. The script will normalize it and add the ADOC `/api` prefix when needed.

Example:

```bash
--adoc-url customer.poc.acceldatasolutions.net
```

Environment variables are also supported:

```bash
export ADOC_URL="customer.poc.acceldatasolutions.net"
export ADOC_API_KEY_FILE="./customer_API_Key.csv"
export ADOC_TENANT_ID="customer-tenant"
export ADOC_TEMPLATE_GROUP_NAME="Customer Notifications"
```

Optional identity headers can also be supplied with:

```bash
export ADOC_USER_ID="<user-id>"
export ADOC_USERNAME="<username>"
```

## List Policies

Use `manage_policies.py` to inventory policies in an account.

```bash
python3 manage_policies.py list \
  --adoc-url <account-url> \
  --api-key-file <api-key.csv> \
  --policy-type all
```

List only Data Quality policies:

```bash
python3 manage_policies.py list \
  --adoc-url <account-url> \
  --api-key-file <api-key.csv> \
  --policy-type data-quality
```

List only Data Freshness policies:

```bash
python3 manage_policies.py list \
  --adoc-url <account-url> \
  --api-key-file <api-key.csv> \
  --policy-type data-freshness
```

If an environment routes catalog APIs under `/api`, add:

```bash
--api-prefix api
```

## Update One Policy

Dry run first. This prints the mutating request without sending it.

```bash
python3 manage_policies.py update \
  --adoc-url <account-url> \
  --api-key-file <api-key.csv> \
  --policy-type data-quality \
  --policy-name Customer_DQ_Policy \
  --payload-file policy_update.json \
  --dry-run
```

Update by ID:

```bash
python3 manage_policies.py update \
  --adoc-url <account-url> \
  --api-key-file <api-key.csv> \
  --policy-type data-freshness \
  --policy-id 14718 \
  --set-enabled false \
  --dry-run
```

For Data Freshness, you can also resolve the policy from an asset ID:

```bash
python3 manage_policies.py update \
  --adoc-url <account-url> \
  --api-key-file <api-key.csv> \
  --policy-type data-freshness \
  --asset-id 1202692 \
  --set-scheduled true \
  --schedule "0 2 * * *" \
  --dry-run
```

## Update A Group Of Policies

Use `update-matching` with filters. Non-dry-run group updates require `--yes`.

```bash
python3 manage_policies.py update-matching \
  --adoc-url <account-url> \
  --api-key-file <api-key.csv> \
  --policy-type data-quality \
  --name-contains prod \
  --payload-file policy_update.json \
  --dry-run
```

Then run the same command without `--dry-run` and with `--yes` after reviewing the output.

## List Template Groups

Use this first when you do not know the template group ID.

```bash
python3 update_notification_templates.py \
  --adoc-url <account-url> \
  --tenant-id <tenant-id> \
  --api-key-file <api-key.csv> \
  --list-template-groups
```

The output shows IDs and names. Save the ID for export and update commands.

## Export Slack Templates

```bash
python3 update_notification_templates.py \
  --adoc-url <account-url> \
  --tenant-id <tenant-id> \
  --api-key-file <api-key.csv> \
  --template-group-id <template-group-id> \
  --channel slack \
  --export-templates \
  --export-dir ./slack_templates
```

This writes one JSON file per Slack template and creates a `_manifest.json` file. The manifest records the source type, channel, template group ID, and template ID.

## Export Email Templates

```bash
python3 update_notification_templates.py \
  --adoc-url <account-url> \
  --tenant-id <tenant-id> \
  --api-key-file <api-key.csv> \
  --template-group-id <template-group-id> \
  --channel email \
  --export-templates \
  --export-dir ./email_templates
```

## Export From All Template Groups

Use this when you are still discovering where templates live.

```bash
python3 update_notification_templates.py \
  --adoc-url <account-url> \
  --tenant-id <tenant-id> \
  --api-key-file <api-key.csv> \
  --channel slack \
  --export-templates \
  --export-all-template-groups \
  --export-dir ./all_slack_templates
```

The script creates one subdirectory per template group.

## Edit Templates

After export, edit the JSON files in:

```text
slack_templates/
email_templates/
```

Slack templates usually contain Slack Block Kit JSON or a Freemarker-rendered JSON string.

Email templates usually contain HTML content and may include a `subject` field.

Freemarker variables are expected and should be preserved unless the change specifically requires editing them.

## Dry Run Before Updating

Always dry run first. This prints the PUT/POST requests the script would send without mutating ADOC.

Slack example:

```bash
python3 update_notification_templates.py \
  --adoc-url <account-url> \
  --tenant-id <tenant-id> \
  --api-key-file <api-key.csv> \
  --template-group-id <template-group-id> \
  --channel slack \
  --template-dir ./slack_templates \
  --dry-run
```

Email example:

```bash
python3 update_notification_templates.py \
  --adoc-url <account-url> \
  --tenant-id <tenant-id> \
  --api-key-file <api-key.csv> \
  --template-group-id <template-group-id> \
  --channel email \
  --template-dir ./email_templates \
  --dry-run
```

If `--source-type` is omitted, the script uses `_manifest.json` in the template directory when present. That means it will update every template listed in the manifest.

## Push All Templates

Slack:

```bash
python3 update_notification_templates.py \
  --adoc-url <account-url> \
  --tenant-id <tenant-id> \
  --api-key-file <api-key.csv> \
  --template-group-id <template-group-id> \
  --channel slack \
  --template-dir ./slack_templates
```

Email:

```bash
python3 update_notification_templates.py \
  --adoc-url <account-url> \
  --tenant-id <tenant-id> \
  --api-key-file <api-key.csv> \
  --template-group-id <template-group-id> \
  --channel email \
  --template-dir ./email_templates
```

## Push One Specific Template

Use `--source-type` to limit the update to one template.

```bash
python3 update_notification_templates.py \
  --adoc-url <account-url> \
  --tenant-id <tenant-id> \
  --api-key-file <api-key.csv> \
  --template-group-id <template-group-id> \
  --channel slack \
  --template-dir ./slack_templates \
  --source-type data_quality
```

Multiple source types are allowed:

```bash
--source-type data_quality --source-type crawler
```

Comma-separated values are also allowed:

```bash
--source-type data_quality,crawler,profile
```

## Create Or Reuse A Template Group By Name

If you do not pass `--template-group-id`, the script can use `--template-group-name`.

```bash
python3 update_notification_templates.py \
  --adoc-url <account-url> \
  --tenant-id <tenant-id> \
  --api-key-file <api-key.csv> \
  --template-group-name "Customer Notifications" \
  --channel slack \
  --template-dir ./slack_templates
```

For update/export/debug commands, the group name must already exist. For the normal push flow, the script will find an existing group by name or create it if needed.

## Wire Notification Channel Groups

Template groups are not useful until notification channel groups reference them. If needed, wire channel groups after templates are created or updated.

```bash
python3 update_notification_templates.py \
  --adoc-url <account-url> \
  --tenant-id <tenant-id> \
  --api-key-file <api-key.csv> \
  --template-group-id <template-group-id> \
  --wire-channel-groups \
  --namespace-id <namespace-id>
```

You can narrow the update:

```bash
--channel-group-id <channel-group-id>
--channel-group-name-contains "prod"
```

Run this with `--dry-run` first.

## Troubleshooting

If ADOC returns HTML instead of JSON, check `--adoc-url`. For most environments, use only the host name and let the script add `/api`.

If a template update returns HTTP 400, keep the default update payload style:

```bash
--update-payload-style contents_only
```

This is the default because it matches the tested update behavior for the ADOC notification template endpoint.

If only a few templates export, verify that the templates have content in ADOC for the selected channel. Empty or uninitialized templates may not return the same way as edited templates.

## Airflow ADOC Connectivity Smoke DAG

The repository includes an end-to-end Airflow DAG at:

```bash
dags/adoc_aruba_connectivity_smoke.py
```

Copy or sync this file into your Airflow `dags/` folder. The DAG expects the `acceldata-sdk` and `acceldata-airflow-sdk` packages to be installed in the Airflow environment.

For Docker-based Airflow, install the packages in the Airflow containers used by the scheduler, webserver, and worker. If you only have `docker-compose.yml` and no Dockerfile, add `_PIP_ADDITIONAL_REQUIREMENTS` to the shared Airflow environment block.

Many Airflow Compose files have an `x-airflow-common` section. Add the requirement there:

```yaml
x-airflow-common:
  &airflow-common
  environment:
    &airflow-common-env
    _PIP_ADDITIONAL_REQUIREMENTS: "acceldata-sdk acceldata-airflow-sdk"
```

If your file already has `_PIP_ADDITIONAL_REQUIREMENTS`, append the two packages to the existing value. Then recreate Airflow:

```bash
docker compose up -d
```

Verify the imports in the scheduler container:

```bash
docker compose exec airflow-scheduler python -c "import acceldata_airflow_sdk, acceldata_sdk; print('ok')"
```

If you run CeleryExecutor, verify the worker container too:

```bash
docker compose exec airflow-worker python -c "import acceldata_airflow_sdk, acceldata_sdk; print('ok')"
```

For a quick non-persistent test, you can install inside running containers instead, but this will be lost when containers are recreated:

```bash
docker compose exec airflow-scheduler pip install acceldata-sdk acceldata-airflow-sdk
docker compose exec airflow-worker pip install acceldata-sdk acceldata-airflow-sdk
docker compose exec airflow-webserver pip install acceldata-sdk acceldata-airflow-sdk
```

By default, the DAG uses an Airflow HTTP connection named:

```text
aruba_acceldata_connection
```

Configure that connection with:

- `Host`: Aruba ADOC tenant URL, for example `https://<tenant-host>`
- `Login`: ADOC access key
- `Password`: ADOC secret key
- `Extra`: optional JSON such as:

```json
{
  "ADOC_TENANT_ID": "<tenant-id>",
  "ENABLE_VERSION_CHECK": false,
  "TORCH_CONNECTION_TIMEOUT_MS": 10000,
  "TORCH_READ_TIMEOUT_MS": 20000
}
```

The DAG has four tasks:

```text
validate_airflow_connection
torch_pipeline_initializer
validate_adoc_http_connection
finalize_adoc_pipeline_success
```

`validate_airflow_connection` checks that the `aruba_acceldata_connection` connection is visible inside the Airflow task runtime before ADOC creates a pipeline run. `TorchInitializer` starts the ADOC pipeline run, the direct HTTP smoke-test task validates tenant connectivity, and `finalize_adoc_pipeline_success` explicitly ends the ADOC root span and marks the pipeline run `COMPLETED`. The DAG also has a failure callback that attempts to mark the ADOC pipeline run `FAILED` if a task fails after initialization.

The smoke task intentionally does not use the SDK `@job` decorator because the decorator can fall back to `torch.acceldata.local` unless the SDK environment variables are also configured in every Airflow container.

If you later add `@job`-decorated tasks, set these environment variables in Docker Compose as well:

```text
TORCH_CATALOG_URL
TORCH_ACCESS_KEY
TORCH_SECRET_KEY
```

You can override these DAG values with Airflow Variables or environment variables:

```text
ADOC_AIRFLOW_CONNECTION_ID
ADOC_AIRFLOW_PIPELINE_UID
ADOC_AIRFLOW_PIPELINE_NAME
ADOC_AIRFLOW_PIPELINE_OWNER
ADOC_AIRFLOW_PIPELINE_TEAM
ADOC_AIRFLOW_CODE_LOCATION
ADOC_AIRFLOW_SMOKE_PATHS
```

`ADOC_AIRFLOW_SMOKE_PATHS` is a comma-separated list of GET paths to try. The default tries both the direct and `/api`-prefixed catalog rules endpoint.

## Repository Safety

The `.gitignore` is configured to avoid committing common secret files, including:

- API key CSV files.
- `.env` files.
- local shell environment files.
- private key/certificate files.
- `arubausdcdpv2_env.sh`.

Before committing, always check:

```bash
git status
```

Only commit the script, docs, non-secret examples, and template files that are safe to share.
