# adoc_bulk_onboard.py

Bulk-invites users to an ADOC tenant and assigns them to groups, driven by a CSV file.

It authenticates with `accessKey` / `secretKey` HTTP headers, resolves group names from
the CSV to Keycloak group IDs via `GET /admin/api/groups`, then calls
`POST /admin/api/users/invite-users`. Since the invite API applies one `groups` array to
every email in a call, the script groups users by their exact set of groups and sends one
(or more, if batched) API call per distinct group combination.

> **Invitation emails are sent by default.** Any `--apply` run emails every invited user
> unless you pass `--no-send-email`. Use `--no-send-email` for test/dry runs against the
> real API.

## Requirements

- Python 3.9+ (standard library only, no dependencies to install)

## CSV format

Each row is an email followed by one or more group names:

```csv
email,group1,group2
alice@example.com,Analysts
bob@example.com,Analysts,Admins
carol@example.com,Admins
```

- A header row is optional — if the first cell in the first row doesn't contain `@`, it's
  skipped.
- Blank lines are skipped.
- Duplicate `(email, group)` pairs on the same row are silently de-duplicated.
- If the same email appears on multiple rows, all of its groups are combined.

## Credentials

The script needs three values: `ADOC_URL`, `ADOC_ACCESS_KEY`, `ADOC_SECRET_KEY`.

They can come from (in order of precedence):

1. Command-line flags (`--url` for the URL only)
2. Process environment variables
3. A `.env` file (default: `./.env`, override with `--env-file`)

Example `.env` file:

```
ADOC_URL=https://your-tenant.acceldata.app
ADOC_ACCESS_KEY=your-access-key
ADOC_SECRET_KEY=your-secret-key
```

Keys are never written to disk by this script — only read from the environment or the
`.env` file you provide.

## Options

| Option | Description |
|---|---|
| `csv_file` (positional) | Path to the CSV file; each row is an email followed by one or more group names. |
| `--url URL` | ADOC tenant base URL. Overrides `ADOC_URL` from the environment or `.env` file. |
| `--env-file PATH` | Path to a credentials file (default: `.env`). Process environment variables still take precedence over this file. |
| `--batch-size N` | Maximum number of invitations per API call (default: `100`). Each distinct group combination gets its own batch(es). |
| `--limit N` | Only process the first N distinct users, keeping each selected user's full group list intact. Useful for a small test run before onboarding everyone. |
| `--send-email` | Have ADOC email invited users (default behavior). |
| `--no-send-email` | Suppress invitation emails — useful for a first dry-ish run against the real API without spamming users. |
| `--apply` | Actually call the ADOC API. Without this flag, the script only previews what it would do. |
| `--access-key-header NAME` | HTTP header name used for the access key (default: `accessKey`). |
| `--secret-key-header NAME` | HTTP header name used for the secret key (default: `secretKey`). |

`--send-email` and `--no-send-email` are mutually exclusive.

## Examples

Preview only (no `--apply`, no credentials required) — shows the planned users, group
combinations, and batch counts without calling the API:

```bash
python3 adoc_bulk_onboard.py users.csv
```

Apply for real, using credentials from `.env` in the current directory:

```bash
python3 adoc_bulk_onboard.py users.csv --apply
```

Apply using a specific tenant URL, overriding `.env`/environment:

```bash
python3 adoc_bulk_onboard.py users.csv --apply --url https://your-tenant.acceldata.app
```

Apply using a credentials file that isn't named `.env`:

```bash
python3 adoc_bulk_onboard.py users.csv --apply --env-file secrets/prod.env
```

Test against the real API on just the first 3 users, without sending invite emails:

```bash
python3 adoc_bulk_onboard.py users.csv --apply --limit 3 --no-send-email
```

Explicitly send invite emails (same as the default, shown here for clarity):

```bash
python3 adoc_bulk_onboard.py users.csv --apply --send-email
```

Send invitations in smaller batches of 20 per call instead of the default 100:

```bash
python3 adoc_bulk_onboard.py users.csv --apply --batch-size 20
```

Combine several options — preview only the first 5 users with a batch size of 2, to sanity
check batching logic before a real run:

```bash
python3 adoc_bulk_onboard.py users.csv --limit 5 --batch-size 2
```

Use non-default header names for the access/secret keys, if your tenant expects different
header names:

```bash
python3 adoc_bulk_onboard.py users.csv --apply \
  --access-key-header X-Access-Key \
  --secret-key-header X-Secret-Key
```

Provide credentials entirely via environment variables instead of a `.env` file:

```bash
export ADOC_URL=https://your-tenant.acceldata.app
export ADOC_ACCESS_KEY=your-access-key
export ADOC_SECRET_KEY=your-secret-key
python3 adoc_bulk_onboard.py users.csv --apply
```

## Exit codes

- `0` — success (preview shown, or all apply batches submitted successfully)
- `1` — an error occurred (invalid CSV, missing credentials, unknown group name, one or
  more failed API batches, etc.). Details are printed to stderr.

## Tests

```bash
python3 -m pytest test_adoc_bulk_onboard.py
```
