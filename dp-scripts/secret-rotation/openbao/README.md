# OpenBao Workflow

Automated secret rotation using OpenBao vault for centralized credential management.

## Quick Start

### Complete Automation (Recommended) 🚀

**If you have AWS IAM permissions**, use the complete end-to-end workflow:

```bash
export BAO_ADDR='https://bao-node-1.acceldatasolutions.net:8200'
export BAO_ROLE_ID_RW='your-write-role-id'
export BAO_SECRET_ID_RW='your-write-secret-id'
export BAO_ROLE_ID_RO='your-read-role-id'
export BAO_SECRET_ID_RO='your-read-secret-id'

# Dry-run first
./0-rotate-aws-and-sync.sh --dry-run \
  se-demo-user aws-keys/poc/adoc/se-demo \
  fijiusdcdpv2 global-storage globalstorage.json

# Execute with old key cleanup
./0-rotate-aws-and-sync.sh --delete-old-key \
  se-demo-user aws-keys/poc/adoc/se-demo \
  fijiusdcdpv2 global-storage globalstorage.json
```

This single script handles: AWS key rotation → OpenBao update → K8s update → old key cleanup.

---

### Manual Steps (If you already have new AWS keys)

### Step 1: Update Credentials in OpenBao Vault

```bash
export BAO_ADDR='https://bao-node-1.acceldatasolutions.net:8200'
export BAO_ROLE_ID_RW='your-write-role-id'
export BAO_SECRET_ID_RW='your-write-secret-id'

# Dry-run first
./1-update-vault.sh --dry-run aws-keys/poc/adoc/se-demo 'AKIA_NEW_KEY' 'new_secret'

# Execute
./1-update-vault.sh aws-keys/poc/adoc/se-demo 'AKIA_NEW_KEY' 'new_secret'
```

### Step 2: Update Kubernetes Secrets

```bash
export BAO_ADDR='https://bao-node-1.acceldatasolutions.net:8200'
export BAO_ROLE_ID_RO='your-read-role-id'
export BAO_SECRET_ID_RO='your-read-secret-id'

# Dry-run first
./2-update-k8s-secrets.sh --dry-run \
  --access-key-field AWS_ACCESS_KEY_ID \
  --secret-key-field AWS_SECRET_ACCESS_KEY \
  fijiusdcdpv2 global-storage globalstorage.json aws-keys/poc/adoc/se-demo

# Execute
./2-update-k8s-secrets.sh \
  --access-key-field AWS_ACCESS_KEY_ID \
  --secret-key-field AWS_SECRET_ACCESS_KEY \
  fijiusdcdpv2 global-storage globalstorage.json aws-keys/poc/adoc/se-demo
```

## Scripts

- **0-rotate-aws-and-sync.sh** - 🚀 Complete automation: AWS rotation → OpenBao → K8s (requires AWS IAM + OpenBao read/write)
- **1-update-vault.sh** - Update AWS credentials in OpenBao (requires write access)
- **2-update-k8s-secrets.sh** - Fetch from OpenBao and update Kubernetes (requires read access)

## Prerequisites

- OpenBao CLI (`bao`) installed
- Two sets of AppRole credentials:
  - Read-write (BAO_ROLE_ID_RW/BAO_SECRET_ID_RW) for vault updates
  - Read-only (BAO_ROLE_ID_RO/BAO_SECRET_ID_RO) for K8s updates
- kubectl configured for target cluster

See [main README](../README.md) for full documentation.
