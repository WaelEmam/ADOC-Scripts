#!/bin/bash

################################################################################
# Script: 0-rotate-aws-and-sync.sh
# Purpose: End-to-end AWS credential rotation workflow
#
# Workflow:
#   1. Create new AWS IAM access key for specified user
#   2. Update OpenBao vault with new credentials (calls 1-update-vault.sh)
#   3. Update Kubernetes secrets from OpenBao (calls 2-update-k8s-secrets.sh)
#   4. (Optional) Delete old AWS access key after successful propagation
#
# Key Functions:
#   - Uses AWS CLI to rotate IAM user access keys
#   - Integrates with existing OpenBao and K8s update scripts
#   - Safety checks before deleting old keys
#   - Supports dry-run mode for safe preview
#
# Dependencies:
#   - aws CLI (AWS command-line tool)
#   - ./1-update-vault.sh (OpenBao vault update)
#   - ./2-update-k8s-secrets.sh (K8s secret update)
#   - jq (JSON processor)
#
# Usage: ./0-rotate-aws-and-sync.sh [OPTIONS] <aws-username> <openbao-secret-path> <k8s-namespace> <k8s-secret-name> <k8s-key-name>
################################################################################

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
    echo "Usage: $0 [OPTIONS] <aws-username> <openbao-secret-path> <k8s-namespace> <k8s-secret-name> <k8s-key-name>"
    echo ""
    echo "Description:"
    echo "  Complete end-to-end AWS credential rotation workflow:"
    echo "  1. Create new AWS IAM access key"
    echo "  2. Update OpenBao vault"
    echo "  3. Update Kubernetes secrets"
    echo "  4. (Optional) Delete old AWS key"
    echo ""
    echo "Options:"
    echo "  --dry-run              Preview changes without applying them"
    echo "  --delete-old-key       Delete old AWS access key after successful rotation"
    echo "  --aws-profile          AWS CLI profile to use (default: default)"
    echo "  --aws-only             Rotate AWS keys only, don't update OpenBao or K8s"
    echo "  --access-key-field     Field name for access key (default: AWS_ACCESS_KEY_ID)"
    echo "  --secret-key-field     Field name for secret key (default: AWS_SECRET_ACCESS_KEY)"
    echo "  --skip-k8s             Update OpenBao only, skip K8s update"
    echo "  -h, --help             Show this help message"
    echo ""
    echo "Required Environment Variables (for OpenBao):"
    echo "  BAO_ADDR               OpenBao server address"
    echo "  BAO_ROLE_ID_RW         AppRole Role ID for read-write (vault update)"
    echo "  BAO_SECRET_ID_RW       AppRole Secret ID for read-write (vault update)"
    echo "  BAO_ROLE_ID_RO         AppRole Role ID for read-only (K8s update)"
    echo "  BAO_SECRET_ID_RO       AppRole Secret ID for read-only (K8s update)"
    echo ""
    echo "Examples:"
    echo "  # Test AWS rotation only (no OpenBao/K8s update)"
    echo "  $0 --aws-only se-demo-user"
    echo ""
    echo "  # Dry-run full rotation"
    echo "  $0 --dry-run se-demo-user aws-keys/poc/adoc/se-demo \\"
    echo "    fijiusdcdpv2 global-storage globalstorage.json"
    echo ""
    echo "  # Execute rotation and delete old key"
    echo "  $0 --delete-old-key se-demo-user aws-keys/poc/adoc/se-demo \\"
    echo "    fijiusdcdpv2 global-storage globalstorage.json"
    echo ""
    echo "  # Update OpenBao only (skip K8s)"
    echo "  $0 --skip-k8s se-demo-user aws-keys/poc/adoc/se-demo \\"
    echo "    fijiusdcdpv2 global-storage globalstorage.json"
    exit 1
}

# Default values
DRY_RUN=false
DELETE_OLD_KEY=false
AWS_PROFILE="default"
AWS_ONLY=false
ACCESS_KEY_FIELD="AWS_ACCESS_KEY_ID"
SECRET_KEY_FIELD="AWS_SECRET_ACCESS_KEY"
SKIP_K8S=false

# Parse options
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --delete-old-key)
            DELETE_OLD_KEY=true
            shift
            ;;
        --aws-profile)
            AWS_PROFILE="$2"
            shift 2
            ;;
        --aws-only)
            AWS_ONLY=true
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
        --skip-k8s)
            SKIP_K8S=true
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
AWS_USERNAME=${1:-}
OPENBAO_SECRET_PATH=${2:-}
K8S_NAMESPACE=${3:-}
K8S_SECRET_NAME=${4:-}
K8S_KEY_NAME=${5:-}

# Validate arguments
if [ -z "$AWS_USERNAME" ]; then
    echo -e "${RED}Error: Missing required argument: aws-username${NC}"
    echo ""
    usage
fi

if [ "$AWS_ONLY" == false ] && [ -z "$OPENBAO_SECRET_PATH" ]; then
    echo -e "${RED}Error: Missing required argument: openbao-secret-path${NC}"
    echo ""
    usage
fi

if [ "$AWS_ONLY" == false ] && [ "$SKIP_K8S" == false ] && ([ -z "$K8S_NAMESPACE" ] || [ -z "$K8S_SECRET_NAME" ] || [ -z "$K8S_KEY_NAME" ]); then
    echo -e "${RED}Error: K8s arguments required unless --skip-k8s or --aws-only is specified${NC}"
    echo ""
    usage
fi

# Check required tools
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: 'aws' CLI is not installed or not in PATH${NC}"
    echo "Install AWS CLI: https://aws.amazon.com/cli/"
    exit 1
fi

if ! command -v jq &> /dev/null; then
    echo -e "${RED}Error: jq is not installed or not in PATH${NC}"
    echo "Install jq: brew install jq (macOS) or apt-get install jq (Linux)"
    exit 1
fi

# Check dependent scripts (only if not --aws-only)
if [ "$AWS_ONLY" == false ]; then
    UPDATE_VAULT_SCRIPT="$SCRIPT_DIR/1-update-vault.sh"
    UPDATE_K8S_SCRIPT="$SCRIPT_DIR/2-update-k8s-secrets.sh"

    if [ ! -f "$UPDATE_VAULT_SCRIPT" ]; then
        echo -e "${RED}Error: 1-update-vault.sh not found at $UPDATE_VAULT_SCRIPT${NC}"
        exit 1
    fi

    if [ "$SKIP_K8S" == false ] && [ ! -f "$UPDATE_K8S_SCRIPT" ]; then
        echo -e "${RED}Error: 2-update-k8s-secrets.sh not found at $UPDATE_K8S_SCRIPT${NC}"
        exit 1
    fi
fi

echo -e "${CYAN}======================================================================${NC}"
if [ "$AWS_ONLY" == true ]; then
    echo -e "${CYAN}AWS Credential Rotation (AWS Only)${NC}"
else
    echo -e "${CYAN}End-to-End AWS Credential Rotation${NC}"
fi
echo -e "${CYAN}======================================================================${NC}"
echo ""
echo "Configuration:"
echo "  AWS User:        $AWS_USERNAME"
echo "  AWS Profile:     $AWS_PROFILE"
if [ "$AWS_ONLY" == false ]; then
    echo "  OpenBao Path:    $OPENBAO_SECRET_PATH"
    if [ "$SKIP_K8S" == false ]; then
        echo "  K8s Namespace:   $K8S_NAMESPACE"
        echo "  K8s Secret:      $K8S_SECRET_NAME"
        echo "  K8s Key:         $K8S_KEY_NAME"
    fi
fi
echo ""
echo "Options:"
echo "  Mode:            $([ "$DRY_RUN" == true ] && echo 'DRY-RUN' || echo 'EXECUTE')"
if [ "$AWS_ONLY" == true ]; then
    echo "  AWS Only:        true (skip OpenBao and K8s)"
else
    echo "  Delete Old Key:  $DELETE_OLD_KEY"
    echo "  Skip K8s Update: $SKIP_K8S"
fi
echo ""

# ============================================================================
# STEP 1: List existing AWS access keys
# ============================================================================
echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}Step 1: Check Existing AWS Access Keys${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

echo -e "${YELLOW}Fetching existing access keys for user: $AWS_USERNAME${NC}"

if ! EXISTING_KEYS=$(aws iam list-access-keys --user-name "$AWS_USERNAME" --profile "$AWS_PROFILE" 2>/tmp/aws-list-err); then
    echo -e "${RED}✗ Failed to list access keys${NC}"
    echo ""
    echo "Error details:"
    cat /tmp/aws-list-err
    rm -f /tmp/aws-list-err
    exit 1
fi

KEY_COUNT=$(echo "$EXISTING_KEYS" | jq -r '.AccessKeyMetadata | length')
echo -e "${GREEN}✓ Found $KEY_COUNT existing access key(s)${NC}"
echo ""

if [ "$KEY_COUNT" -ge 2 ]; then
    echo -e "${YELLOW}⚠ Warning: User already has 2 access keys (AWS limit)${NC}"
    echo "Existing keys:"
    echo "$EXISTING_KEYS" | jq -r '.AccessKeyMetadata[] | "  - \(.AccessKeyId) (Status: \(.Status), Created: \(.CreateDate))"'
    echo ""
    echo "You must delete one key before creating a new one."
    echo "Use: aws iam delete-access-key --user-name $AWS_USERNAME --access-key-id <KEY_ID>"
    exit 1
fi

# Store old key ID for potential deletion
OLD_KEY_ID=""
if [ "$KEY_COUNT" -eq 1 ]; then
    OLD_KEY_ID=$(echo "$EXISTING_KEYS" | jq -r '.AccessKeyMetadata[0].AccessKeyId')
    echo "Current key: $OLD_KEY_ID"
    echo ""
fi

# ============================================================================
# STEP 2: Create new AWS access key
# ============================================================================
echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}Step 2: Create New AWS Access Key${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

if [ "$DRY_RUN" == true ]; then
    echo -e "${YELLOW}DRY-RUN: Would create new access key for $AWS_USERNAME${NC}"
    echo ""
    echo "Command that would be executed:"
    echo "  aws iam create-access-key --user-name $AWS_USERNAME --profile $AWS_PROFILE"
    echo ""
    echo -e "${YELLOW}Stopping here in dry-run mode${NC}"
    exit 0
fi

echo -e "${YELLOW}Creating new access key for user: $AWS_USERNAME${NC}"

if ! NEW_KEY_JSON=$(aws iam create-access-key --user-name "$AWS_USERNAME" --profile "$AWS_PROFILE" 2>/tmp/aws-create-err); then
    echo -e "${RED}✗ Failed to create new access key${NC}"
    echo ""
    echo "Error details:"
    cat /tmp/aws-create-err
    rm -f /tmp/aws-create-err
    exit 1
fi

NEW_ACCESS_KEY=$(echo "$NEW_KEY_JSON" | jq -r '.AccessKey.AccessKeyId')
NEW_SECRET_KEY=$(echo "$NEW_KEY_JSON" | jq -r '.AccessKey.SecretAccessKey')

echo -e "${GREEN}✓ Successfully created new access key${NC}"
echo "  Access Key ID: $NEW_ACCESS_KEY"
echo "  Secret Key: ******* (${#NEW_SECRET_KEY} characters)"
echo ""

# ============================================================================
# AWS_ONLY MODE: Exit here and display credentials
# ============================================================================
if [ "$AWS_ONLY" == true ]; then
    echo -e "${GREEN}======================================================================${NC}"
    echo -e "${GREEN}✓ AWS Key Rotation Completed (AWS Only Mode)${NC}"
    echo -e "${GREEN}======================================================================${NC}"
    echo ""
    echo "New AWS Credentials:"
    echo "  Access Key ID:     $NEW_ACCESS_KEY"
    echo "  Secret Access Key: $NEW_SECRET_KEY"
    echo ""
    if [ -n "$OLD_KEY_ID" ]; then
        echo "Old Key (still active):"
        echo "  Access Key ID: $OLD_KEY_ID"
        echo ""
        echo "To delete the old key:"
        echo "  aws iam delete-access-key --user-name $AWS_USERNAME --access-key-id $OLD_KEY_ID"
        echo ""
    fi
    echo "Next steps:"
    echo "  - Test the new credentials"
    echo "  - Update OpenBao: ./1-update-vault.sh $OPENBAO_SECRET_PATH '$NEW_ACCESS_KEY' '$NEW_SECRET_KEY'"
    echo "  - Or run full workflow: ./0-rotate-aws-and-sync.sh (without --aws-only)"
    echo ""
    exit 0
fi

# ============================================================================
# STEP 3: Update OpenBao vault
# ============================================================================
echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}Step 3: Update OpenBao Vault${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

echo -e "${YELLOW}Calling 1-update-vault.sh...${NC}"
echo ""

if ! "$UPDATE_VAULT_SCRIPT" \
    --access-key-field "$ACCESS_KEY_FIELD" \
    --secret-key-field "$SECRET_KEY_FIELD" \
    "$OPENBAO_SECRET_PATH" \
    "$NEW_ACCESS_KEY" \
    "$NEW_SECRET_KEY"; then
    echo -e "${RED}✗ Failed to update OpenBao vault${NC}"
    echo ""
    echo -e "${YELLOW}⚠ New AWS key was created but not stored in OpenBao!${NC}"
    echo "New Access Key ID: $NEW_ACCESS_KEY"
    echo "You may want to delete it: aws iam delete-access-key --user-name $AWS_USERNAME --access-key-id $NEW_ACCESS_KEY"
    exit 1
fi

echo ""
echo -e "${GREEN}✓ OpenBao vault updated successfully${NC}"
echo ""

# ============================================================================
# STEP 4: Update Kubernetes secrets (if not skipped)
# ============================================================================
if [ "$SKIP_K8S" == false ]; then
    read -p "Press Enter to continue to Kubernetes update..."
    echo ""

    echo -e "${BLUE}======================================================================${NC}"
    echo -e "${BLUE}Step 4: Update Kubernetes Secrets${NC}"
    echo -e "${BLUE}======================================================================${NC}"
    echo ""

    echo -e "${YELLOW}Calling 2-update-k8s-secrets.sh...${NC}"
    echo ""

    if ! "$UPDATE_K8S_SCRIPT" \
        --access-key-field "$ACCESS_KEY_FIELD" \
        --secret-key-field "$SECRET_KEY_FIELD" \
        "$K8S_NAMESPACE" \
        "$K8S_SECRET_NAME" \
        "$K8S_KEY_NAME" \
        "$OPENBAO_SECRET_PATH"; then
        echo -e "${RED}✗ Failed to update Kubernetes secrets${NC}"
        echo ""
        echo -e "${YELLOW}⚠ Vault is updated but K8s is not!${NC}"
        echo "You can manually run: $UPDATE_K8S_SCRIPT"
        exit 1
    fi

    echo ""
    echo -e "${GREEN}✓ Kubernetes secrets updated successfully${NC}"
    echo ""
else
    echo -e "${YELLOW}Skipping Kubernetes update (--skip-k8s flag)${NC}"
    echo ""
fi

# ============================================================================
# STEP 5: Delete old AWS key (if requested and exists)
# ============================================================================
if [ "$DELETE_OLD_KEY" == true ] && [ -n "$OLD_KEY_ID" ]; then
    echo -e "${BLUE}======================================================================${NC}"
    echo -e "${BLUE}Step 5: Delete Old AWS Access Key${NC}"
    echo -e "${BLUE}======================================================================${NC}"
    echo ""

    echo -e "${YELLOW}⚠ You are about to delete the old access key: $OLD_KEY_ID${NC}"
    echo ""
    read -p "Type 'DELETE' to confirm deletion, or press Enter to skip: " CONFIRM

    if [ "$CONFIRM" == "DELETE" ]; then
        echo ""
        echo -e "${YELLOW}Deleting old access key: $OLD_KEY_ID${NC}"

        if aws iam delete-access-key --user-name "$AWS_USERNAME" --access-key-id "$OLD_KEY_ID" --profile "$AWS_PROFILE" 2>/tmp/aws-delete-err; then
            echo -e "${GREEN}✓ Successfully deleted old access key${NC}"
        else
            echo -e "${RED}✗ Failed to delete old access key${NC}"
            echo ""
            echo "Error details:"
            cat /tmp/aws-delete-err
            rm -f /tmp/aws-delete-err
            echo ""
            echo "You can manually delete it later:"
            echo "  aws iam delete-access-key --user-name $AWS_USERNAME --access-key-id $OLD_KEY_ID"
        fi
    else
        echo ""
        echo -e "${YELLOW}Skipped deletion of old access key${NC}"
        echo "Old key ID: $OLD_KEY_ID"
        echo ""
        echo "You can delete it later with:"
        echo "  aws iam delete-access-key --user-name $AWS_USERNAME --access-key-id $OLD_KEY_ID"
    fi
    echo ""
elif [ "$DELETE_OLD_KEY" == true ] && [ -z "$OLD_KEY_ID" ]; then
    echo -e "${YELLOW}No old key to delete (user had 0 keys)${NC}"
    echo ""
fi

# ============================================================================
# SUMMARY
# ============================================================================
echo -e "${GREEN}======================================================================${NC}"
echo -e "${GREEN}✓ End-to-End Rotation Completed Successfully!${NC}"
echo -e "${GREEN}======================================================================${NC}"
echo ""
echo "Summary:"
echo "  ✓ Created new AWS access key: $NEW_ACCESS_KEY"
echo "  ✓ Updated OpenBao vault: $OPENBAO_SECRET_PATH"
if [ "$SKIP_K8S" == false ]; then
    echo "  ✓ Updated Kubernetes secret: $K8S_NAMESPACE/$K8S_SECRET_NAME"
    echo "  ✓ Restarted deployments and verified health"
fi
if [ "$DELETE_OLD_KEY" == true ] && [ -n "$OLD_KEY_ID" ]; then
    echo "  ✓ Deleted old AWS access key: $OLD_KEY_ID"
elif [ -n "$OLD_KEY_ID" ]; then
    echo "  ⚠ Old key still active: $OLD_KEY_ID (delete manually if needed)"
fi
echo ""
echo "The rotation is complete. New credentials are live in:"
echo "  - AWS IAM (user: $AWS_USERNAME)"
echo "  - OpenBao vault ($OPENBAO_SECRET_PATH)"
if [ "$SKIP_K8S" == false ]; then
    echo "  - Kubernetes ($K8S_NAMESPACE/$K8S_SECRET_NAME)"
    echo "  - Running pods (restarted with new credentials)"
fi
echo ""
