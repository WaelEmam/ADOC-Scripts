#!/bin/bash

# Script to fetch secrets from OpenBao and rotate them in Kubernetes
# Usage: ./rotate-from-openbao.sh [OPTIONS] <namespace> <k8s-secret-name> <k8s-key-name> <openbao-secret-path>

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Function to display usage
usage() {
    echo "Usage: $0 [OPTIONS] <k8s-namespace> <k8s-secret-name> <k8s-key-name> <openbao-secret-path>"
    echo ""
    echo "Description:"
    echo "  Fetches AWS credentials from OpenBao and updates Kubernetes secret."
    echo "  Integrates with OpenBao for centralized secret management."
    echo ""
    echo "Options:"
    echo "  --dry-run              Preview all changes without applying them"
    echo "  --skip-restart         Update secret but don't restart deployments"
    echo "  --skip-wait            Don't wait for pods to be ready after restart"
    echo "  --access-key-field     Field name in OpenBao for access key (default: access_key)"
    echo "  --secret-key-field     Field name in OpenBao for secret key (default: secret_key)"
    echo "  -h, --help             Show this help message"
    echo ""
    echo "Required Environment Variables:"
    echo "  BAO_ADDR               OpenBao server address (e.g., https://bao-node-1.example.com:8200)"
    echo "  BAO_ROLE_ID_RO         AppRole Role ID for read-only authentication"
    echo "  BAO_SECRET_ID_RO       AppRole Secret ID for read-only authentication"
    echo ""
    echo "Examples:"
    echo "  # Dry-run to preview changes"
    echo "  export BAO_ADDR='https://bao-node-1.example.com:8200'"
    echo "  export BAO_ROLE_ID_RO='your-read-only-role-id'"
    echo "  export BAO_SECRET_ID_RO='your-read-only-secret-id'"
    echo ""
    echo "  $0 --dry-run <namespace> global-storage globalstorage.json kv/aws/s3-credentials"
    echo ""
    echo "  # Execute the rotation"
    echo "  $0 <namespace> global-storage globalstorage.json kv/aws/s3-credentials"
    echo ""
    echo "  # Custom field names"
    echo "  $0 --access-key-field MEASURE_RESULT_FS_S3A_ACCESS_KEY \\"
    echo "     --secret-key-field MEASURE_RESULT_FS_S3A_SECRET_KEY \\"
    echo "     <namespace> global-storage globalstorage.json kv/aws/s3-credentials"
    exit 1
}

# Default values
DRY_RUN=false
SKIP_RESTART=false
SKIP_WAIT=false
ACCESS_KEY_FIELD="access_key"
SECRET_KEY_FIELD="secret_key"

# Parse options
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-restart)
            SKIP_RESTART=true
            shift
            ;;
        --skip-wait)
            SKIP_WAIT=true
            shift
            ;;
        --access-key-field)
            ACCESS_KEY_FIELD="$2"
            shift 2
            ;;
        --secret-key-field)
            SECRET_KEY_FIELD="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            break
            ;;
    esac
done

# Remaining arguments
K8S_NAMESPACE=${1:-}
K8S_SECRET_NAME=${2:-}
K8S_KEY_NAME=${3:-}
OPENBAO_SECRET_PATH=${4:-}

# Validate arguments
if [ -z "$K8S_NAMESPACE" ] || [ -z "$K8S_SECRET_NAME" ] || [ -z "$K8S_KEY_NAME" ] || [ -z "$OPENBAO_SECRET_PATH" ]; then
    echo -e "${RED}Error: Missing required arguments${NC}"
    echo ""
    usage
fi

# Check required environment variables
if [ -z "$BAO_ADDR" ]; then
    echo -e "${RED}Error: BAO_ADDR environment variable is not set${NC}"
    echo "Set it to your OpenBao server address, e.g.:"
    echo "export BAO_ADDR='https://bao-node-1.example.com:8200'"
    exit 1
fi

if [ -z "$BAO_ROLE_ID_RO" ]; then
    echo -e "${RED}Error: BAO_ROLE_ID_RO environment variable is not set${NC}"
    echo "This script requires read-only OpenBao credentials"
    exit 1
fi

if [ -z "$BAO_SECRET_ID_RO" ]; then
    echo -e "${RED}Error: BAO_SECRET_ID_RO environment variable is not set${NC}"
    echo "This script requires read-only OpenBao credentials"
    exit 1
fi

# Check if required tools are available
if ! command -v bao &> /dev/null; then
    echo -e "${RED}Error: 'bao' CLI is not installed or not in PATH${NC}"
    echo ""
    echo "Install OpenBao CLI from: https://openbao.org/docs/install/"
    exit 1
fi

if ! command -v jq &> /dev/null; then
    echo -e "${RED}Error: jq is not installed or not in PATH${NC}"
    echo "Install jq: brew install jq (macOS) or apt-get install jq (Linux)"
    exit 1
fi

# Check if rotation script exists
ROTATION_SCRIPT="$SCRIPT_DIR/rotate-secret-and-restart.sh"
if [ ! -f "$ROTATION_SCRIPT" ]; then
    echo -e "${RED}Error: rotate-secret-and-restart.sh not found in $SCRIPT_DIR${NC}"
    exit 1
fi

echo -e "${CYAN}======================================================================${NC}"
echo -e "${CYAN}OpenBao to Kubernetes Secret Rotation${NC}"
echo -e "${CYAN}======================================================================${NC}"
echo ""
echo "OpenBao Configuration:"
echo "  Address:    $BAO_ADDR"
echo "  Secret:     $OPENBAO_SECRET_PATH"
echo ""
echo "Kubernetes Configuration:"
echo "  Namespace:  $K8S_NAMESPACE"
echo "  Secret:     $K8S_SECRET_NAME"
echo "  Key:        $K8S_KEY_NAME"
echo ""
echo "Mode: $([ "$DRY_RUN" == true ] && echo 'DRY-RUN' || echo 'EXECUTE')"
echo ""

# ============================================================================
# STEP 1: Authenticate to OpenBao
# ============================================================================
echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}Step 1: Authenticate to OpenBao${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

echo -e "${YELLOW}Authenticating to OpenBao (read-only)...${NC}"

# Authenticate and capture the token
if ! BAO_TOKEN=$(bao write -field=token auth/approle/login \
    role_id="$BAO_ROLE_ID_RO" secret_id="$BAO_SECRET_ID_RO" 2>/tmp/bao-auth-err); then
    echo -e "${RED}✗ Failed to authenticate to OpenBao${NC}"
    echo ""
    echo "Error details:"
    cat /tmp/bao-auth-err
    rm -f /tmp/bao-auth-err
    exit 1
fi

export BAO_TOKEN

echo -e "${GREEN}✓ Successfully authenticated to OpenBao${NC}"
echo ""

# Setup token cleanup on exit
trap 'bao token revoke -self >/dev/null 2>&1 || true; rm -f /tmp/bao-*.tmp' EXIT

# ============================================================================
# STEP 2: Fetch secrets from OpenBao
# ============================================================================
echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}Step 2: Fetch AWS Credentials from OpenBao${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

echo -e "${YELLOW}Fetching secrets from OpenBao...${NC}"

# Fetch the secret in JSON format
if ! SECRET_JSON=$(bao kv get -format=json "$OPENBAO_SECRET_PATH" 2>/tmp/bao-read-err); then
    echo -e "${RED}✗ Failed to read secret from OpenBao${NC}"
    echo ""
    echo "Error details:"
    cat /tmp/bao-read-err
    rm -f /tmp/bao-read-err
    exit 1
fi

# Parse the secret data (handle KV v2 envelope)
# KV v2 structure: .data.data.<field>
# KV v1 structure: .data.<field>
ACCESS_KEY=$(echo "$SECRET_JSON" | jq -r ".data.data.${ACCESS_KEY_FIELD} // .data.${ACCESS_KEY_FIELD} // empty")
SECRET_KEY=$(echo "$SECRET_JSON" | jq -r ".data.data.${SECRET_KEY_FIELD} // .data.${SECRET_KEY_FIELD} // empty")

if [ -z "$ACCESS_KEY" ] || [ "$ACCESS_KEY" == "null" ]; then
    echo -e "${RED}✗ Failed to extract access key from OpenBao secret${NC}"
    echo ""
    echo "Expected field: ${ACCESS_KEY_FIELD}"
    echo "Available fields:"
    echo "$SECRET_JSON" | jq -r '.data.data // .data | keys[]'
    exit 1
fi

if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" == "null" ]; then
    echo -e "${RED}✗ Failed to extract secret key from OpenBao secret${NC}"
    echo ""
    echo "Expected field: ${SECRET_KEY_FIELD}"
    echo "Available fields:"
    echo "$SECRET_JSON" | jq -r '.data.data // .data | keys[]'
    exit 1
fi

echo -e "${GREEN}✓ Successfully retrieved credentials from OpenBao${NC}"
echo ""
echo "Retrieved fields:"
echo "  - ${ACCESS_KEY_FIELD}: ${ACCESS_KEY:0:10}... (${#ACCESS_KEY} characters)"
echo "  - ${SECRET_KEY_FIELD}: ******* (${#SECRET_KEY} characters)"
echo ""

# ============================================================================
# STEP 3: Update Kubernetes Secret
# ============================================================================
echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}Step 3: Update Kubernetes Secret and Restart Deployments${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

# Build arguments for the rotation script
ROTATION_ARGS=()
if [ "$DRY_RUN" == true ]; then
    ROTATION_ARGS+=("--dry-run")
fi
if [ "$SKIP_RESTART" == true ]; then
    ROTATION_ARGS+=("--skip-restart")
fi
if [ "$SKIP_WAIT" == true ]; then
    ROTATION_ARGS+=("--skip-wait")
fi

ROTATION_ARGS+=(
    "$K8S_NAMESPACE"
    "$K8S_SECRET_NAME"
    "$K8S_KEY_NAME"
    "MEASURE_RESULT_FS_S3A_ACCESS_KEY=${ACCESS_KEY}"
    "MEASURE_RESULT_FS_S3A_SECRET_KEY=${SECRET_KEY}"
)

# Execute the rotation
"$ROTATION_SCRIPT" "${ROTATION_ARGS[@]}"

ROTATION_EXIT_CODE=$?

# ============================================================================
# SUMMARY
# ============================================================================
echo ""
echo -e "${GREEN}======================================================================${NC}"
if [ "$DRY_RUN" == true ]; then
    echo -e "${GREEN}Dry-run completed - No changes were made${NC}"
    echo -e "${GREEN}Remove --dry-run flag to execute${NC}"
else
    if [ $ROTATION_EXIT_CODE -eq 0 ]; then
        echo -e "${GREEN}✓ Secret rotation completed successfully!${NC}"
    else
        echo -e "${RED}✗ Secret rotation failed${NC}"
        exit $ROTATION_EXIT_CODE
    fi
fi
echo -e "${GREEN}======================================================================${NC}"
echo ""

if [ "$DRY_RUN" == false ] && [ $ROTATION_EXIT_CODE -eq 0 ]; then
    echo "Summary:"
    echo "  ✓ Retrieved credentials from OpenBao ($OPENBAO_SECRET_PATH)"
    echo "  ✓ Updated Kubernetes secret '$K8S_SECRET_NAME' in namespace '$K8S_NAMESPACE'"
    if [ "$SKIP_RESTART" == false ]; then
        echo "  ✓ Restarted deployments with new credentials"
    fi
    echo ""
    echo "Next steps:"
    echo "  - Verify applications are working correctly"
    echo "  - Check logs if needed: kubectl logs -n $K8S_NAMESPACE <pod-name>"
    echo "  - OpenBao token will be automatically revoked on script exit"
fi
