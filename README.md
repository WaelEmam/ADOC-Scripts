# Disclaimer: 
This repository is an independent, personal project. It is not owned, endorsed, or officially maintained by Acceldata. 
Scripts here are provided as-is, with no warranty; use at your own risk against your own ADOC environments.

# ADOC Scripts

A collection of independent Python tools and an Airflow DAG for operating ADOC tenants:
notification templates, policy management, bulk user onboarding, and connectivity
monitoring. Each tool lives in its own folder with its own README.

## Repo Contents

- [notification-templates/](notification-templates/README.md): export, create, update,
  and wire ADOC Slack/Email notification templates. Includes the `slack_templates/` and
  `email_templates/` payloads it operates on.
- [policy-management/](policy-management/README.md): list and update ADOC policies,
  including Data Quality and Data Freshness/Data Cadence policies.
- [user-management/](user-management/README.md): bulk-invite users to an ADOC tenant and
  assign them to groups from a CSV file.
- [airflow/](airflow/README.md): Airflow DAG for Aruba ADOC connectivity validation.

## Requirements

All scripts use Python 3.9+ (`user-management`) or 3.10+ (`notification-templates`,
`policy-management`) and only the standard library — no third-party packages to install.
See each folder's README for tool-specific requirements.

## Credentials

Every tool authenticates against an ADOC tenant using an access key and secret key, but
takes them differently — see each folder's README for its exact credential format
(CSV/key file vs. `.env`/environment variables). Never commit API keys, `.env` files, or
other customer/account-specific secrets to Git.

## Repository Safety

The `.gitignore` is configured to avoid committing common secret files, including:

- API key CSV files.
- `.env` files.
- local shell environment files.
- private key/certificate files.
- `arubausdcdpv2_env.sh`.
- the `keys/` directory.

Before committing, always check:

```bash
git status
```

Only commit scripts, docs, non-secret examples, and template files that are safe to
share.
