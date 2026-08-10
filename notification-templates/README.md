# ADOC Notification Template Automation

A Python script for exporting and updating ADOC notification templates. It is mainly used
when a team needs to make controlled changes to Slack or Email notification templates
across ADOC policy source types, then push those changes back to a customer/account
environment.

The main script is:

```bash
update_notification_templates.py
```

It works with ADOC notification template groups. A template group is the container, and
each template inside the group is tied to a notification channel, such as Slack or Email,
and a `sourceType`, such as `DATA_QUALITY`, `CRAWLER`, or `PROFILE`.

## Table Of Contents

- [What The Script Does](#what-the-script-does)
- [Requirements](#requirements)
- [Credentials](#credentials)
- [Common Inputs](#common-inputs)
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

No third-party Python packages are required. The script uses only the Python standard
library.

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

If `--api-key-file` is omitted, the script will automatically use the file in the current
directory when exactly one file matches one of these patterns:

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

You can use a hostname without `https://`. The script will normalize it and add the ADOC
`/api` prefix when needed.

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

This writes one JSON file per Slack template and creates a `_manifest.json` file. The
manifest records the source type, channel, template group ID, and template ID.

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

Freemarker variables are expected and should be preserved unless the change specifically
requires editing them.

## Dry Run Before Updating

Always dry run first. This prints the PUT/POST requests the script would send without
mutating ADOC.

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

If `--source-type` is omitted, the script uses `_manifest.json` in the template directory
when present. That means it will update every template listed in the manifest.

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

For update/export/debug commands, the group name must already exist. For the normal push
flow, the script will find an existing group by name or create it if needed.

## Wire Notification Channel Groups

Template groups are not useful until notification channel groups reference them. If
needed, wire channel groups after templates are created or updated.

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

If ADOC returns HTML instead of JSON, check `--adoc-url`. For most environments, use only
the host name and let the script add `/api`.

If a template update returns HTTP 400, keep the default update payload style:

```bash
--update-payload-style contents_only
```

This is the default because it matches the tested update behavior for the ADOC
notification template endpoint.

If only a few templates export, verify that the templates have content in ADOC for the
selected channel. Empty or uninitialized templates may not return the same way as edited
templates.
