# Kubernetes Secret Rotation Scripts

A collection of bash scripts for managing Kubernetes secrets and restarting deployments in the Acceldata dataplane environment.

## Overview

These scripts provide a complete workflow for rotating secrets in Kubernetes and ensuring affected deployments pick up the new values. The scripts are designed to be safe with dry-run modes, automatic backups, and verification steps.

**New:** Now includes OpenBao integration for centralized secret management!

## Which Workflow Should I Use?

### **Use OpenBao Workflow** ✅ (Recommended)
**When:** Your FE team manages secrets in OpenBao vault

**Benefits:**
- ✅ Single source of truth for credentials
- ✅ Automatic credential fetching
- ✅ Centralized rotation by FE team
- ✅ Audit trail in OpenBao
- ✅ No credentials in command history

**Scripts to use:**
1. `openbao/1-update-vault.sh` - Update credentials in OpenBao
2. `openbao/2-update-k8s-secrets.sh` - Pull from OpenBao and update K8s

---

### **Use Manual Workflow**
**When:** You don't have OpenBao access OR need to manually enter credentials

**Scripts to use:**
1. `manual/rotate-and-restart.sh` - Manually enter credentials

---

## Script Architecture & Dependencies

### Directory Structure
```
secret-rotation/
├── openbao/                  # OpenBao workflow scripts
│   ├── 1-update-vault.sh    # Update credentials in OpenBao vault
│   └── 2-update-k8s-secrets.sh     # Fetch from OpenBao → update K8s
│
├── manual/                   # Manual workflow scripts
│   └── rotate-and-restart.sh # Manual credential entry workflow
│
├── lib/                      # Shared library scripts
│   ├── update-k8s-secret.sh  # Core K8s secret operations
│   └── restart-deployments.sh # Core K8s deployment restart
│
└── README.md                 # This file
```

### Script Relationships

**OpenBao Workflow (Automated):**
```
openbao/2-update-k8s-secrets.sh
  ├─> OpenBao vault (fetch credentials)
  ├─> lib/update-k8s-secret.sh (update K8s secret)
  └─> lib/restart-deployments.sh (restart pods)
```

**Manual Workflow:**
```
manual/rotate-and-restart.sh
  ├─> User provides credentials
  ├─> lib/update-k8s-secret.sh (update K8s secret)
  └─> lib/restart-deployments.sh (restart pods)
```

**Key Points:**
- ✅ **Independent workflows:** OpenBao and Manual workflows don't depend on each other
- ✅ **Shared libraries:** Both workflows use the same `lib/` scripts for K8s operations
- ✅ **No circular dependencies:** Clean unidirectional dependency flow
- ✅ **Modular design:** Each script has a single, clear responsibility

---

## Scripts

### 1. `openbao/1-update-vault.sh` (OpenBao Write)

**Purpose:** Update AWS credentials in OpenBao vault. Requires write permissions.

**What it does:**
1. Authenticates to OpenBao using AppRole (read-write)
2. Reads existing secret to preserve other fields
3. Updates AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
4. Preserves other fields like AWS_REGION
5. Verifies the update
6. Automatically revokes OpenBao token on exit

**Usage:**
```bash
./openbao/1-update-vault.sh [OPTIONS] <openbao-secret-path> <access-key> <secret-key>
```

**Options:**
- `--dry-run` - Preview changes without applying them
- `--access-key-field` - Field name for access key (default: AWS_ACCESS_KEY_ID)
- `--secret-key-field` - Field name for secret key (default: AWS_SECRET_ACCESS_KEY)
- `--preserve-fields` - Preserve other fields (default: true)
- `-h, --help` - Show help message

**Required Environment Variables:**
```bash
export BAO_ADDR='https://bao-node-1.acceldatasolutions.net:8200'
export BAO_ROLE_ID_RW='your-write-role-id'
export BAO_SECRET_ID_RW='your-write-secret-id'
```

**Example:**
```bash
# Set up OpenBao write credentials
export BAO_ADDR='https://bao-node-1.acceldatasolutions.net:8200'
export BAO_ROLE_ID_RW='write-role-id'
export BAO_SECRET_ID_RW='write-secret-id'

# Dry-run to preview changes
./openbao/1-update-vault.sh --dry-run \
  aws-keys/poc/adoc/se-demo \
  'AWS_NEW_ACCESS_KEY' \
  'AWS_NEW_SECRET_KEY'

# Execute the update
./openbao/1-update-vault.sh \
  aws-keys/poc/adoc/se-demo \
  'AWS_NEW_ACCESS_KEY' \
  'AWS_NEW_SECRET_KEY'
```

**Prerequisites:**
- OpenBao CLI (`bao`) installed and in PATH
- AppRole credentials with **write** permissions
- Access to update the OpenBao secret path

---

### 2. `openbao/2-update-k8s-secrets.sh` (OpenBao Read → K8s)

**Purpose:** Fetch credentials from OpenBao vault and update Kubernetes secrets automatically.

**What it does:**
1. Authenticates to OpenBao using AppRole
2. Fetches AWS credentials (access key & secret key) from OpenBao
3. Updates Kubernetes secret with the fetched credentials
4. Restarts affected deployments
5. Automatically revokes OpenBao token on exit

**Usage:**
```bash
./openbao/2-update-k8s-secrets.sh [OPTIONS] <k8s-namespace> <k8s-secret-name> <k8s-key-name> <openbao-secret-path>
```

**Options:**
- `--dry-run` - Preview all changes without applying them
- `--skip-restart` - Update secret but don't restart deployments
- `--skip-wait` - Don't wait for pods to be ready after restart
- `--access-key-field` - Field name in OpenBao for access key (default: access_key)
- `--secret-key-field` - Field name in OpenBao for secret key (default: secret_key)
- `-h, --help` - Show help message

**Required Environment Variables:**
```bash
export BAO_ADDR='https://bao-node-1.acceldatasolutions.net:8200'
export BAO_ROLE_ID_RO='your-read-only-role-id'
export BAO_SECRET_ID_RO='your-read-only-secret-id'
```

**Example:**
```bash
# Set up OpenBao read-only credentials
export BAO_ADDR='https://bao-node-1.acceldatasolutions.net:8200'
export BAO_ROLE_ID_RO='read-role-id'
export BAO_SECRET_ID_RO='read-secret-id'

# Dry-run to preview changes
./openbao/2-update-k8s-secrets.sh --dry-run \
  --access-key-field AWS_ACCESS_KEY_ID \
  --secret-key-field AWS_SECRET_ACCESS_KEY \
  fijiusdcdpv2 global-storage globalstorage.json aws-keys/poc/adoc/se-demo

# Execute the rotation
./openbao/2-update-k8s-secrets.sh \
  --access-key-field AWS_ACCESS_KEY_ID \
  --secret-key-field AWS_SECRET_ACCESS_KEY \
  fijiusdcdpv2 global-storage globalstorage.json aws-keys/poc/adoc/se-demo
```

**Prerequisites:**
- OpenBao CLI (`bao`) installed and in PATH
- AppRole credentials with **read** permissions
- Access to the OpenBao secret path containing AWS credentials

---

### 3. `rotate-secret-and-restart.sh` (Manual Entry Workflow)

**Purpose:** Complete end-to-end workflow for rotating secrets and restarting deployments.

**What it does:**
1. Displays current secret values
2. Compares new values with existing values (exits early if no changes)
3. Updates the secret with automatic backup
4. Shows diff of changes
5. Restarts affected deployments
6. Waits for all pods to be ready

**Usage:**
```bash
./manual/rotate-and-restart.sh [OPTIONS] <namespace> <secret-name> <key-name> <key=value pairs...>
```

**Options:**
- `--dry-run` - Preview all changes without applying them (recommended first step)
- `--skip-restart` - Update secret but don't restart deployments
- `--skip-wait` - Don't wait for pods to be ready after restart
- `-h, --help` - Show help message

**Example:**
```bash
# Dry-run to preview changes
./manual/rotate-and-restart.sh --dry-run <namespace> global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIANEWACCESSKEY123' \
  'MEASURE_RESULT_FS_S3A_SECRET_KEY=newSecretKeyHere456'

# Execute the rotation
./manual/rotate-and-restart.sh <namespace> global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIANEWACCESSKEY123' \
  'MEASURE_RESULT_FS_S3A_SECRET_KEY=newSecretKeyHere456'
```

---

### 4. `update-k8s-secret.sh` (Secret Management)

**Purpose:** Read, merge, or replace Kubernetes secrets with base64 encoding.

**What it does:**
- Read and display secret values (decoded)
- Merge specific fields into existing JSON secrets
- Replace entire secret content
- Compare and detect if values already match
- Create automatic backups before updates
- Verify updates after applying

**Usage:**
```bash
./lib/update-k8s-secret.sh [OPTIONS] <namespace> <secret-name> <key-name> [data]
```

**Modes:**
- `--read` - Read and display current secret value
- `--merge` - Merge specific fields (default for key=value format)
- `--replace` - Replace entire secret content

**Options:**
- `--dry-run` - Show changes without applying
- `--no-backup` - Skip creating backup file (not recommended)
- `-h, --help` - Show help message

**Examples:**

**Read a secret:**
```bash
./lib/update-k8s-secret.sh --read <namespace> global-storage globalstorage.json
```

**List all keys in a secret:**
```bash
./lib/update-k8s-secret.sh --read <namespace> global-storage
```

**Merge specific fields:**
```bash
./lib/update-k8s-secret.sh --merge <namespace> global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=newkey' \
  'MEASURE_RESULT_FS_S3A_SECRET_KEY=newsecret'
```

**Merge with dry-run:**
```bash
./lib/update-k8s-secret.sh --merge --dry-run <namespace> global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_REGION=us-west-2'
```

**Replace entire content:**
```bash
./lib/update-k8s-secret.sh --replace <namespace> global-storage globalstorage.json \
  '{"key":"value","another":"data"}'
```

**Replace from file:**
```bash
./lib/update-k8s-secret.sh --replace <namespace> global-storage globalstorage.json \
  @/path/to/config.json
```

---

### 5. `restart-deployments.sh` (Deployment Management)

**Purpose:** Scale down and up Kubernetes deployments to pick up new secret values.

**What it does:**
1. Verifies all deployments exist
2. Scales down deployments to 0 replicas
3. Waits for all pods to terminate
4. Scales up to target replica counts
5. Waits for all pods to be ready
6. Shows final deployment status

**Configured Deployments:**
- `acceldata-dataplane-analysis-service` → 1 replica
- `acceldata-dataplane-analysis-standalone-service` → 1 replica
- `sparkoperator` → 1 replica
- `acceldata-dataplane-torch-monitor-service` → 2 replicas

**Usage:**
```bash
./lib/restart-deployments.sh [OPTIONS] <namespace>
```

**Options:**
- `--dry-run` - Show what would happen without executing
- `--wait-timeout` - Timeout in seconds for waiting (default: 300)
- `--skip-wait` - Don't wait for pods to be ready
- `-h, --help` - Show help message

**Examples:**

**Dry-run to preview actions:**
```bash
./lib/restart-deployments.sh --dry-run <namespace>
```

**Execute the restart:**
```bash
./lib/restart-deployments.sh <namespace>
```

**Skip waiting (fire and forget):**
```bash
./lib/restart-deployments.sh --skip-wait <namespace>
```

**Custom timeout:**
```bash
./lib/restart-deployments.sh --wait-timeout 600 <namespace>
```

---

## Common Workflows

### Workflow 1: Complete OpenBao Rotation (Recommended)

**Scenario:** FE/SE team manages AWS credentials in OpenBao vault. Update credentials in vault, then propagate to Kubernetes.

**Part A: Update Credentials in OpenBao**
```bash
# Set up OpenBao write authentication
export BAO_ADDR='https://bao-node-1.acceldatasolutions.net:8200'
export BAO_ROLE_ID_RW='your-write-role-id'
export BAO_SECRET_ID_RW='your-write-secret-id'

# Step 1: Dry-run to preview OpenBao update
./openbao/1-update-vault.sh --dry-run \
  aws-keys/poc/adoc/se-demo \
  'AKIA_NEW_ACCESS_KEY' \
  'new-secret-key-value'

# Step 2: Update credentials in OpenBao
./openbao/1-update-vault.sh \
  aws-keys/poc/adoc/se-demo \
  'AKIA_NEW_ACCESS_KEY' \
  'new-secret-key-value'
```

**Part B: Propagate to Kubernetes**
```bash
# Set up OpenBao read authentication
export BAO_ADDR='https://bao-node-1.acceldatasolutions.net:8200'
export BAO_ROLE_ID_RO='your-read-role-id'
export BAO_SECRET_ID_RO='your-read-secret-id'

# Step 3: Dry-run K8s update
./openbao/2-update-k8s-secrets.sh --dry-run \
  --access-key-field AWS_ACCESS_KEY_ID \
  --secret-key-field AWS_SECRET_ACCESS_KEY \
  fijiusdcdpv2 global-storage globalstorage.json aws-keys/poc/adoc/se-demo

# Step 4: Update Kubernetes and restart deployments
./openbao/2-update-k8s-secrets.sh \
  --access-key-field AWS_ACCESS_KEY_ID \
  --secret-key-field AWS_SECRET_ACCESS_KEY \
  fijiusdcdpv2 global-storage globalstorage.json aws-keys/poc/adoc/se-demo
```

**Benefits of OpenBao workflow:**
- ✅ Single source of truth for credentials
- ✅ Centralized rotation by FE team
- ✅ Audit trail in OpenBao
- ✅ No credentials in command history
- ✅ Automatic credential fetching (no manual copy/paste)
- ✅ Multiple K8s namespaces can pull from same OpenBao secret

### Workflow 2: Rotate S3 Access Keys (Manual)

**Scenario:** AWS credentials have been rotated and you need to manually enter them.

```bash
# Step 1: Check current values
./lib/update-k8s-secret.sh --read <namespace> global-storage globalstorage.json

# Step 2: Dry-run the rotation
./manual/rotate-and-restart.sh --dry-run <namespace> global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIA...' \
  'MEASURE_RESULT_FS_S3A_SECRET_KEY=...'

# Step 3: Execute the rotation
./manual/rotate-and-restart.sh <namespace> global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIA...' \
  'MEASURE_RESULT_FS_S3A_SECRET_KEY=...'

# Step 4: Verify
./lib/update-k8s-secret.sh --read <namespace> global-storage globalstorage.json
```

### Workflow 3: Update Single Field

**Scenario:** Only the S3 region needs to be updated.

```bash
# Update just the region
./manual/rotate-and-restart.sh <namespace> global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_REGION=us-west-2'
```

### Workflow 4: Manual Step-by-Step

**Scenario:** You want more control over each step.

```bash
# 1. Update secret only (no restart)
./lib/update-k8s-secret.sh --merge <namespace> global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=newkey'

# 2. Verify the update
./lib/update-k8s-secret.sh --read <namespace> global-storage globalstorage.json

# 3. Manually restart deployments when ready
./lib/restart-deployments.sh <namespace>
```

### Workflow 5: Check Without Changes

**Scenario:** Verify if values need updating.

```bash
# Try to update with same values - script will detect no changes
./manual/rotate-and-restart.sh <namespace> global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=currentvalue'

# Output: "No changes detected - No update is necessary"
```

---

## Safety Features

### Automatic Backups
- Secrets are automatically backed up to `/tmp/` before any update
- Backup filename format: `<namespace>-<secret-name>-backup-YYYYMMDD-HHMMSS.yaml`
- Use `kubectl apply -f /tmp/<backup-file>` to restore if needed

### Change Detection
- Scripts compare new values with existing values
- Exits early if no changes detected (avoids unnecessary restarts)
- Uses normalized JSON comparison (ignores formatting differences)

### Dry-Run Mode
- Preview all changes before applying
- Shows diffs, base64 values, and deployment impacts
- No modifications made to cluster

### Verification
- Secrets are verified after updates
- Deployment status checked after restarts
- Clear success/failure indicators

### Interactive Confirmations
- `rotate-secret-and-restart.sh` pauses between major steps
- Gives you time to review before proceeding
- Ctrl+C to cancel at any point

---

## Requirements

### Prerequisites
- `kubectl` - Kubernetes command-line tool
- `jq` - JSON processor
- `base64` - Base64 encoding/decoding (standard on macOS/Linux)
- Bash 3.2+ (macOS compatible)


### Kubernetes Access
- Valid kubeconfig configured (`~/.kube/config`)
- Appropriate RBAC permissions for the target namespace
- Permissions required:
  - Read secrets
  - Update secrets
  - Scale deployments
  - Get deployment status
  - Connect to US DC VPN

---

## Troubleshooting

### "Secret not found"
**Problem:** The secret doesn't exist in the namespace.

**Solution:** Verify namespace and secret name:
```bash
kubectl get secrets -n <namespace>
```

### "Key not found in secret"
**Problem:** The specified key doesn't exist in the secret.

**Solution:** List available keys:
```bash
./lib/update-k8s-secret.sh --read <namespace> <secret-name>
```




### "Timeout waiting for pods"
**Problem:** Pods took too long to be ready.

**Solution:**
- Check pod status: `kubectl get pods -n <namespace>`
- Check pod logs: `kubectl logs -n <namespace> <pod-name>`
- Increase timeout: `./lib/restart-deployments.sh --wait-timeout 600 <namespace>`


---

## Security Considerations

### Sensitive Data Handling
- **Never** commit secrets to git
- **Never** pass secrets on command line in shared/recorded terminals
- Please use environment variables or secure vaults
- Backup files in `/tmp/` contain plaintext secrets - clean them up after verification

### Best Practices
- Always use `--dry-run` first to preview changes
- Verify deployments are healthy after rotation
- Keep backup files until changes are verified
- Clean up backup files after successful rotation

---

## Script Architecture

```
rotate-secret-and-restart.sh (main workflow)
    ├── Calls: update-k8s-secret.sh (to update secrets)
    └── Calls: restart-deployments.sh (to restart deployments)

update-k8s-secret.sh (standalone secret management)
    └── Uses: kubectl, jq, base64

restart-deployments.sh (standalone deployment management)
    └── Uses: kubectl
```

All scripts can be used independently or together as part of the main workflow.
---

## Version History

- **v1.0** - Initial release
  - Secret rotation with merge/replace modes
  - Automatic deployment restart
  - Dry-run support
  - Change detection
  - Automatic backups
  - bash 3.2+ compatibility (macOS)
