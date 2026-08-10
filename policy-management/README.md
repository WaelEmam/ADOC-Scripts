# ADOC Policy Management

A Python script for inventorying and updating ADOC policies across an account, including
Data Quality and Data Freshness/Data Cadence policies.

The main script is:

```bash
manage_policies.py
```

## Table Of Contents

- [Requirements](#requirements)
- [Credentials](#credentials)
- [Common Inputs](#common-inputs)
- [List Policies](#list-policies)
- [Update One Policy](#update-one-policy)
- [Update A Group Of Policies](#update-a-group-of-policies)

## Requirements

- Python 3.10 or newer.
- Network access to the target ADOC URL.
- An ADOC API key file with access key and secret key values.

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
```

You can pass the key file explicitly with `--api-key-file`, or let the script pick it up
automatically when exactly one file in the current directory matches `*API_Key*.csv`,
`*api_key*.csv`, or `*apikey*.csv`.

## Common Inputs

Most commands need these values:

```bash
--adoc-url <account-url>
--api-key-file <api-key.csv>
```

If an environment routes catalog APIs under `/api`, add:

```bash
--api-prefix api
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
