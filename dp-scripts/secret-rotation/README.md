# Kubernetes Secret Rotation Scripts

A collection of bash scripts for managing Kubernetes secrets and restarting deployments in the Acceldata dataplane environment.

## Overview

These scripts provide a complete workflow for rotating secrets in Kubernetes and ensuring affected deployments pick up the new values. The scripts are designed to be safe with dry-run modes, automatic backups, and verification steps.

## Scripts

### 1. `rotate-secret-and-restart.sh` (Main Workflow)

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
./rotate-secret-and-restart.sh [OPTIONS] <namespace> <secret-name> <key-name> <key=value pairs...>
```

**Options:**
- `--dry-run` - Preview all changes without applying them (recommended first step)
- `--skip-restart` - Update secret but don't restart deployments
- `--skip-wait` - Don't wait for pods to be ready after restart
- `-h, --help` - Show help message

**Example:**
```bash
# Dry-run to preview changes
./rotate-secret-and-restart.sh --dry-run partnerusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIANEWACCESSKEY123' \
  'MEASURE_RESULT_FS_S3A_SECRET_KEY=newSecretKeyHere456'

# Execute the rotation
./rotate-secret-and-restart.sh partnerusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIANEWACCESSKEY123' \
  'MEASURE_RESULT_FS_S3A_SECRET_KEY=newSecretKeyHere456'
```

---

### 2. `update-k8s-secret.sh` (Secret Management)

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
./update-k8s-secret.sh [OPTIONS] <namespace> <secret-name> <key-name> [data]
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
./update-k8s-secret.sh --read partnerusdcdpv2 global-storage globalstorage.json
```

**List all keys in a secret:**
```bash
./update-k8s-secret.sh --read partnerusdcdpv2 global-storage
```

**Merge specific fields:**
```bash
./update-k8s-secret.sh --merge partnerusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=newkey' \
  'MEASURE_RESULT_FS_S3A_SECRET_KEY=newsecret'
```

**Merge with dry-run:**
```bash
./update-k8s-secret.sh --merge --dry-run partnerusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_REGION=us-west-2'
```

**Replace entire content:**
```bash
./update-k8s-secret.sh --replace partnerusdcdpv2 global-storage globalstorage.json \
  '{"key":"value","another":"data"}'
```

**Replace from file:**
```bash
./update-k8s-secret.sh --replace partnerusdcdpv2 global-storage globalstorage.json \
  @/path/to/config.json
```

---

### 3. `restart-deployments.sh` (Deployment Management)

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
./restart-deployments.sh [OPTIONS] <namespace>
```

**Options:**
- `--dry-run` - Show what would happen without executing
- `--wait-timeout` - Timeout in seconds for waiting (default: 300)
- `--skip-wait` - Don't wait for pods to be ready
- `-h, --help` - Show help message

**Examples:**

**Dry-run to preview actions:**
```bash
./restart-deployments.sh --dry-run partnerusdcdpv2
```

**Execute the restart:**
```bash
./restart-deployments.sh partnerusdcdpv2
```

**Skip waiting (fire and forget):**
```bash
./restart-deployments.sh --skip-wait partnerusdcdpv2
```

**Custom timeout:**
```bash
./restart-deployments.sh --wait-timeout 600 partnerusdcdpv2
```

---

## Common Workflows

### Workflow 1: Rotate S3 Access Keys

**Scenario:** AWS credentials have been rotated and need to be updated in the dataplane.

```bash
# Step 1: Check current values
./update-k8s-secret.sh --read partnerusdcdpv2 global-storage globalstorage.json

# Step 2: Dry-run the rotation
./rotate-secret-and-restart.sh --dry-run partnerusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIA...' \
  'MEASURE_RESULT_FS_S3A_SECRET_KEY=...'

# Step 3: Execute the rotation
./rotate-secret-and-restart.sh partnerusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIA...' \
  'MEASURE_RESULT_FS_S3A_SECRET_KEY=...'

# Step 4: Verify
./update-k8s-secret.sh --read partnerusdcdpv2 global-storage globalstorage.json
```

### Workflow 2: Update Single Field

**Scenario:** Only the S3 region needs to be updated.

```bash
# Update just the region
./rotate-secret-and-restart.sh partnerusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_REGION=us-west-2'
```

### Workflow 3: Manual Step-by-Step

**Scenario:** You want more control over each step.

```bash
# 1. Update secret only (no restart)
./update-k8s-secret.sh --merge partnerusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=newkey'

# 2. Verify the update
./update-k8s-secret.sh --read partnerusdcdpv2 global-storage globalstorage.json

# 3. Manually restart deployments when ready
./restart-deployments.sh partnerusdcdpv2
```

### Workflow 4: Check Without Changes

**Scenario:** Verify if values need updating.

```bash
# Try to update with same values - script will detect no changes
./rotate-secret-and-restart.sh partnerusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=currentvalue'

# Output: "No changes detected - No update is necessary"
```

---

## Safety Features

### Automatic Backups
- Secrets are automatically backed up to `/tmp/` before any update
- Backup filename format: `<secret-name>-backup-YYYYMMDD-HHMMSS.yaml`
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

### Install Missing Tools

**macOS:**
```bash
brew install kubectl jq
```

**Linux (Ubuntu/Debian):**
```bash
apt-get install kubectl jq
```

### Kubernetes Access
- Valid kubeconfig configured (`~/.kube/config`)
- Appropriate RBAC permissions for the target namespace
- Permissions required:
  - Read secrets
  - Update secrets
  - Scale deployments
  - Get deployment status

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
./update-k8s-secret.sh --read <namespace> <secret-name>
```

### "Invalid JSON format"
**Problem:** The existing secret or new data is not valid JSON.

**Solution:** 
- Check existing secret: `./update-k8s-secret.sh --read <namespace> <secret-name> <key>`
- Validate your JSON: `echo '{"your":"json"}' | jq .`

### "Deployment not found"
**Problem:** One of the configured deployments doesn't exist.

**Solution:** Check deployments in namespace:
```bash
kubectl get deployments -n <namespace>
```

To modify the deployment list, edit `restart-deployments.sh` and update the `DEPLOYMENTS` array.

### "Timeout waiting for pods"
**Problem:** Pods took too long to be ready.

**Solution:**
- Check pod status: `kubectl get pods -n <namespace>`
- Check pod logs: `kubectl logs -n <namespace> <pod-name>`
- Increase timeout: `./restart-deployments.sh --wait-timeout 600 <namespace>`

### Permission Denied
**Problem:** Script is not executable.

**Solution:**
```bash
chmod +x *.sh
```

---

## Security Considerations

### Sensitive Data Handling
- **Never** commit secrets to git
- **Never** pass secrets on command line in shared/recorded terminals
- Consider using environment variables or secure vaults for production
- Backup files in `/tmp/` contain plaintext secrets - clean them up after verification

### Best Practices
1. Always use `--dry-run` first to preview changes
2. Test in non-production environments first
3. Verify deployments are healthy after rotation
4. Keep backup files until changes are verified
5. Clean up backup files after successful rotation
6. Rotate secrets during maintenance windows when possible

### RBAC Requirements
Ensure your Kubernetes user/service account has:
```yaml
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "patch"]
- apiGroups: ["apps"]
  resources: ["deployments", "deployments/scale"]
  verbs: ["get", "list", "patch", "update"]
- apiGroups: ["apps"]
  resources: ["deployments/status"]
  verbs: ["get"]
```

---

## Examples by Use Case

### Example 1: Complete Rotation (Recommended)
```bash
# One command does everything with safety checks
./rotate-secret-and-restart.sh --dry-run partnerusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIANEWACCESSKEY' \
  'MEASURE_RESULT_FS_S3A_SECRET_KEY=newSecretKey'

# If dry-run looks good, execute
./rotate-secret-and-restart.sh partnerusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIANEWACCESSKEY' \
  'MEASURE_RESULT_FS_S3A_SECRET_KEY=newSecretKey'
```

### Example 2: Read-Only Operations
```bash
# See what's currently configured
./update-k8s-secret.sh --read partnerusdcdpv2 global-storage globalstorage.json

# List all secrets in namespace
kubectl get secrets -n partnerusdcdpv2

# List all keys in a specific secret
./update-k8s-secret.sh --read partnerusdcdpv2 global-storage
```

### Example 3: Update Multiple Fields
```bash
# Update bucket, region, and path in one command
./rotate-secret-and-restart.sh partnerusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_BUCKET=new-bucket-name' \
  'MEASURE_RESULT_FS_S3A_REGION=eu-west-1' \
  'MEASURE_RESULT_FS_SAVE_PATH=new-path/'
```

### Example 4: Update Secret Only (No Restart)
```bash
# Update secret but restart deployments later
./rotate-secret-and-restart.sh --skip-restart partnerusdcdpv2 global-storage globalstorage.json \
  'MEASURE_RESULT_FS_S3A_ACCESS_KEY=newkey'

# Later, manually restart when ready
./restart-deployments.sh partnerusdcdpv2
```

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

## Contributing

To modify deployment configurations:
1. Edit `restart-deployments.sh`
2. Update the `DEPLOYMENTS` array:
   ```bash
   DEPLOYMENTS=(
       "deployment-name:replica-count"
       "another-deployment:replica-count"
   )
   ```
3. Test with `--dry-run` first

---

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review script output for error messages
3. Verify Kubernetes access and permissions
4. Check deployment and pod status with `kubectl`

---

## Version History

- **v1.0** - Initial release
  - Secret rotation with merge/replace modes
  - Automatic deployment restart
  - Dry-run support
  - Change detection
  - Automatic backups
  - bash 3.2+ compatibility (macOS)
