#!/bin/bash

# Script to update AWS credentials in OpenBao vault
# Usage: ./update-openbao-secret.sh [OPTIONS] <openbao-secret-path> <access-key> <secret-key>

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Function to display usage
usage() {
    echo "Usage: $0 [OPTIONS] <openbao-secret-path> <access-key> <secret-key>"
    echo ""
    echo "Description:"
    echo "  Updates AWS credentials in OpenBao vault. Requires write permissions."
    echo ""
    echo "Options:"
    echo "  --dry-run              Preview changes without applying them"
    echo "  --access-key-field     Field name for access key (default: AWS_ACCESS_KEY_ID)"
    echo "  --secret-key-field     Field name for secret key (default: AWS_SECRET_ACCESS_KEY)"
    echo "  --preserve-fields      Preserve other fields in the secret (default: true)"
    echo "  -h, --help             Show this help message"
    echo ""
    echo "Required Environment Variables:"
    echo "  BAO_ADDR               OpenBao server address (e.g., https://bao-node-1.example.com:8200)"
    echo "  BAO_ROLE_ID_RW         AppRole Role ID for read-write authentication"
    echo "  BAO_SECRET_ID_RW       AppRole Secret ID for read-write authentication"
    echo ""
    echo "Examples:"
    echo "  # Set up OpenBao credentials (write access)"
    echo "  export BAO_ADDR='https://bao-node-1.example.com:8200'"
    echo "  export BAO_ROLE_ID_RW='your-write-role-id'"
    echo "  export BAO_SECRET_ID_RW='your-write-secret-id'"
    echo ""
    echo "  # Dry-run to preview changes"
    echo "  $0 --dry-run aws-keys/poc/adoc/se-demo AKIA... 'secret-key-value'"
    echo ""
    echo "  # Execute the update"
    echo "  $0 aws-keys/poc/adoc/se-demo AKIA... 'secret-key-value'"
    echo ""
    echo "  # Custom field names"
    echo "  $0 --access-key-field ACCESS_KEY --secret-key-field SECRET_KEY \\"
    echo "     aws-keys/poc/adoc/se-demo AKIA... 'secret-key-value'"
    exit 1
}

# Default values
DRY_RUN=false
ACCESS_KEY_FIELD="AWS_ACCESS_KEY_ID"
SECRET_KEY_FIELD="AWS_SECRET_ACCESS_KEY"
PRESERVE_FIELDS=true

# Parse options
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
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
        --preserve-fields)
            PRESERVE_FIELDS=true
            shift
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
OPENBAO_SECRET_PATH=${1:-}
NEW_ACCESS_KEY=${2:-}
NEW_SECRET_KEY=${3:-}

# Validate arguments
if [ -z "$OPENBAO_SECRET_PATH" ] || [ -z "$NEW_ACCESS_KEY" ] || [ -z "$NEW_SECRET_KEY" ]; then
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

if [ -z "$BAO_ROLE_ID_RW" ]; then
    echo -e "${RED}Error: BAO_ROLE_ID_RW environment variable is not set${NC}"
    echo "This script requires read-write OpenBao credentials"
    exit 1
fi

if [ -z "$BAO_SECRET_ID_RW" ]; then
    echo -e "${RED}Error: BAO_SECRET_ID_RW environment variable is not set${NC}"
    echo "This script requires read-write OpenBao credentials"
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

echo -e "${CYAN}======================================================================${NC}"
echo -e "${CYAN}Update AWS Credentials in OpenBao${NC}"
echo -e "${CYAN}======================================================================${NC}"
echo ""
echo "OpenBao Configuration:"
echo "  Address:    $BAO_ADDR"
echo "  Secret:     $OPENBAO_SECRET_PATH"
echo ""
echo "Update Configuration:"
echo "  Access Key Field: $ACCESS_KEY_FIELD"
echo "  Secret Key Field: $SECRET_KEY_FIELD"
echo "  New Access Key:   ${NEW_ACCESS_KEY:0:10}... (${#NEW_ACCESS_KEY} characters)"
echo "  New Secret Key:   ******* (${#NEW_SECRET_KEY} characters)"
echo "  Preserve Fields:  $PRESERVE_FIELDS"
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

echo -e "${YELLOW}Authenticating to OpenBao (read-write)...${NC}"

# Authenticate and capture the token
if ! BAO_TOKEN=$(bao write -field=token auth/approle/login \
    role_id="$BAO_ROLE_ID_RW" secret_id="$BAO_SECRET_ID_RW" 2>/tmp/bao-auth-err); then
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
# STEP 2: Read existing secret (if preserving fields)
# ============================================================================
echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}Step 2: Read Current Secret${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

EXISTING_SECRET_JSON=""
if [ "$PRESERVE_FIELDS" == true ]; then
    echo -e "${YELLOW}Reading current secret to preserve other fields...${NC}"

    if SECRET_JSON=$(bao kv get -format=json "$OPENBAO_SECRET_PATH" 2>/tmp/bao-read-err); then
        # Extract the data (handle KV v2 envelope)
        EXISTING_SECRET_JSON=$(echo "$SECRET_JSON" | jq -r '.data.data // .data')
        echo -e "${GREEN}✓ Successfully read existing secret${NC}"
        echo ""
        echo "Current fields:"
        echo "$EXISTING_SECRET_JSON" | jq -r 'keys[]' | while read key; do
            if [ "$key" == "$ACCESS_KEY_FIELD" ] || [ "$key" == "$SECRET_KEY_FIELD" ]; then
                echo "  - $key (will be updated)"
            else
                echo "  - $key (will be preserved)"
            fi
        done
    else
        echo -e "${YELLOW}⚠ Secret does not exist yet - will create new secret${NC}"
        EXISTING_SECRET_JSON="{}"
    fi
    echo ""
else
    echo -e "${YELLOW}Preserve fields disabled - will replace entire secret${NC}"
    EXISTING_SECRET_JSON="{}"
    echo ""
fi

# ============================================================================
# STEP 3: Build new secret data
# ============================================================================
echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}Step 3: Build New Secret Data${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

# Start with existing data or empty object
NEW_SECRET_JSON="$EXISTING_SECRET_JSON"

# Update the access key and secret key fields
NEW_SECRET_JSON=$(echo "$NEW_SECRET_JSON" | jq \
    --arg access_key_field "$ACCESS_KEY_FIELD" \
    --arg access_key_value "$NEW_ACCESS_KEY" \
    --arg secret_key_field "$SECRET_KEY_FIELD" \
    --arg secret_key_value "$NEW_SECRET_KEY" \
    '.[$access_key_field] = $access_key_value | .[$secret_key_field] = $secret_key_value')

echo -e "${CYAN}New secret data:${NC}"
echo "$NEW_SECRET_JSON" | jq -r 'keys[]' | while read -r key; do
    if echo "$key" | grep -iq "secret\|key"; then
        echo "  $key = *****"
    else
        value=$(echo "$NEW_SECRET_JSON" | jq -r --arg k "$key" '.[$k]')
        echo "  $key = $value"
    fi
done
echo ""

# ============================================================================
# STEP 4: Show diff
# ============================================================================
if [ "$EXISTING_SECRET_JSON" != "{}" ]; then
    echo -e "${BLUE}======================================================================${NC}"
    echo -e "${BLUE}Changes to be applied:${NC}"
    echo -e "${BLUE}======================================================================${NC}"
    echo ""

    echo -e "${RED}BEFORE:${NC}"
    echo "$EXISTING_SECRET_JSON" | jq .
    echo ""

    echo -e "${GREEN}AFTER:${NC}"
    echo "$NEW_SECRET_JSON" | jq .
    echo ""
fi

# ============================================================================
# DRY RUN MODE
# ============================================================================
if [ "$DRY_RUN" == true ]; then
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}DRY RUN MODE - No changes applied${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    echo "Would execute:"
    echo "  bao kv put $OPENBAO_SECRET_PATH <data>"
    echo ""
    echo -e "${YELLOW}To apply these changes, remove --dry-run flag${NC}"
    exit 0
fi

# ============================================================================
# STEP 5: Write to OpenBao
# ============================================================================
echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}Step 5: Update OpenBao Secret${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

echo -e "${YELLOW}Writing secret to OpenBao...${NC}"

# Write the secret (bao kv put accepts JSON via stdin or as key=value pairs)
# We'll use a temp file to pass the JSON data
TEMP_FILE=$(mktemp)
echo "$NEW_SECRET_JSON" > "$TEMP_FILE"

# Convert JSON to key=value pairs for bao kv put
KV_ARGS=()
while IFS= read -r line; do
    KEY=$(echo "$line" | jq -r '.key')
    VALUE=$(echo "$line" | jq -r '.value')
    KV_ARGS+=("${KEY}=${VALUE}")
done < <(echo "$NEW_SECRET_JSON" | jq -r 'to_entries[] | @json')

if bao kv put "$OPENBAO_SECRET_PATH" "${KV_ARGS[@]}" 2>/tmp/bao-write-err; then
    echo -e "${GREEN}✓ Successfully updated secret in OpenBao${NC}"
    echo ""

    # Verify the write
    echo -e "${YELLOW}Verifying update...${NC}"
    if VERIFY_JSON=$(bao kv get -format=json "$OPENBAO_SECRET_PATH" 2>/dev/null); then
        VERIFY_DATA=$(echo "$VERIFY_JSON" | jq -r '.data.data // .data')
        VERIFY_ACCESS_KEY=$(echo "$VERIFY_DATA" | jq -r --arg field "$ACCESS_KEY_FIELD" '.[$field]')
        VERIFY_SECRET_KEY=$(echo "$VERIFY_DATA" | jq -r --arg field "$SECRET_KEY_FIELD" '.[$field]')

        if [ "$VERIFY_ACCESS_KEY" == "$NEW_ACCESS_KEY" ] && [ "$VERIFY_SECRET_KEY" == "$NEW_SECRET_KEY" ]; then
            echo -e "${GREEN}✓ Verification successful - credentials updated${NC}"
        else
            echo -e "${RED}⚠ Warning: Verification failed - values may not match${NC}"
        fi
    fi
else
    echo -e "${RED}✗ Failed to update secret in OpenBao${NC}"
    echo ""
    echo "Error details:"
    cat /tmp/bao-write-err
    rm -f /tmp/bao-write-err "$TEMP_FILE"
    exit 1
fi

rm -f "$TEMP_FILE"

# ============================================================================
# SUMMARY
# ============================================================================
echo ""
echo -e "${GREEN}======================================================================${NC}"
echo -e "${GREEN}✓ OpenBao secret updated successfully!${NC}"
echo -e "${GREEN}======================================================================${NC}"
echo ""
echo "Summary:"
echo "  ✓ Updated credentials in OpenBao"
echo "  Secret Path: $OPENBAO_SECRET_PATH"
echo "  Updated Fields: $ACCESS_KEY_FIELD, $SECRET_KEY_FIELD"
echo ""
echo "Next steps:"
echo "  - Use rotate-from-openbao.sh to propagate these credentials to Kubernetes"
echo "  - OpenBao token will be automatically revoked on script exit"
