#!/bin/bash

################################################################################
# Script: rotate-and-restart.sh
# Purpose: Manual workflow for rotating K8s secrets with user-provided credentials
#
# Workflow:
#   1. User provides new credentials as key=value pairs
#   2. Update Kubernetes secret using ../lib/update-k8s-secret.sh
#   3. Restart deployments using ../lib/restart-deployments.sh
#
# Dependencies:
#   - ../lib/update-k8s-secret.sh (for K8s secret updates)
#   - ../lib/restart-deployments.sh (for deployment restarts)
#   - kubectl (Kubernetes command-line tool)
#   - jq (JSON processor)
#
# Usage: ./rotate-and-restart.sh [OPTIONS] <namespace> <secret-name> <key-name> <key=value pairs...>
################################################################################

set -e

# ============================================================================
# GLOBAL VARIABLES AND COLOR CODES
# ============================================================================

# Color codes for formatted terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Get script directory for relative path resolution
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ============================================================================
# FUNCTION: usage
# Display help message with usage instructions and examples
# ============================================================================
usage() {
    echo "Usage: $0 [OPTIONS] <namespace> <secret-name> <key-name> <key=value pairs...>"
    echo ""
    echo "Description:"
    echo "  Manual workflow to rotate Kubernetes secrets and restart affected deployments."
    echo "  User provides credentials directly as key=value pairs."
    echo ""
    echo "Options:"
    echo "  --dry-run          Preview all changes without applying them"
    echo "  --skip-restart     Update secret but don't restart deployments"
    echo "  --skip-wait        Don't wait for pods to be ready after restart"
    echo "  -h, --help         Show this help message"
    echo ""
    echo "Workflow Steps:"
    echo "  1. Shows current secret values"
    echo "  2. Updates secret with new values (merge mode)"
    echo "  3. Restarts deployments to pick up new secret values"
    echo ""
    echo "Examples:"
    echo "  # Dry-run to preview all changes"
    echo "  $0 --dry-run fijiusdcdpv2 global-storage globalstorage.json \\"
    echo "    'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIA_NEW_KEY' \\"
    echo "    'MEASURE_RESULT_FS_S3A_SECRET_KEY=new_secret_value'"
    echo ""
    echo "  # Execute the full rotation"
    echo "  $0 fijiusdcdpv2 global-storage globalstorage.json \\"
    echo "    'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIA_NEW_KEY' \\"
    echo "    'MEASURE_RESULT_FS_S3A_SECRET_KEY=new_secret_value'"
    echo ""
    echo "  # Update secret only, skip restart"
    echo "  $0 --skip-restart fijiusdcdpv2 global-storage globalstorage.json \\"
    echo "    'MEASURE_RESULT_FS_S3A_ACCESS_KEY=AKIA_NEW_KEY'"
    exit 1
}

# ============================================================================
# PARSE COMMAND LINE OPTIONS
# Process flags and extract arguments
# ============================================================================

# Default values for optional parameters
DRY_RUN=false
SKIP_RESTART=false
SKIP_WAIT=false

# Parse optional flags
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
        -h|--help)
            usage
            ;;
        *)
            break
            ;;
    esac
done

# Extract positional arguments
NAMESPACE=$1
SECRET_NAME=$2
KEY_NAME=$3
shift 3 2>/dev/null || true
KEY_VALUE_PAIRS=("$@")

# ============================================================================
# VALIDATION: Required Arguments
# ============================================================================
if [ -z "$NAMESPACE" ] || [ -z "$SECRET_NAME" ] || [ -z "$KEY_NAME" ] || [ ${#KEY_VALUE_PAIRS[@]} -eq 0 ]; then
    echo -e "${RED}Error: Missing required arguments${NC}"
    usage
fi

# ============================================================================
# VALIDATION: Dependent Scripts
# Ensure required lib scripts exist
# ============================================================================
UPDATE_SCRIPT="$SCRIPT_DIR/../lib/update-k8s-secret.sh"
RESTART_SCRIPT="$SCRIPT_DIR/../lib/restart-deployments.sh"

if [ ! -f "$UPDATE_SCRIPT" ]; then
    echo -e "${RED}Error: update-k8s-secret.sh not found at $UPDATE_SCRIPT${NC}"
    exit 1
fi

if [ ! -f "$RESTART_SCRIPT" ]; then
    echo -e "${RED}Error: restart-deployments.sh not found at $RESTART_SCRIPT${NC}"
    exit 1
fi

# ============================================================================
# DISPLAY CONFIGURATION
# Show user what will be done
# ============================================================================
echo -e "${CYAN}======================================================================${NC}"
echo -e "${CYAN}Kubernetes Secret Rotation (Manual Entry)${NC}"
echo -e "${CYAN}======================================================================${NC}"
echo ""
echo "Namespace:   $NAMESPACE"
echo "Secret:      $SECRET_NAME"
echo "Key:         $KEY_NAME"
echo "Mode:        $([ "$DRY_RUN" == true ] && echo 'DRY-RUN' || echo 'EXECUTE')"
echo ""
echo "Values to update:"
for pair in "${KEY_VALUE_PAIRS[@]}"; do
    KEY="${pair%%=*}"
    echo "  - $KEY"
done
echo ""

read -p "Press Enter to continue or Ctrl+C to cancel..."
echo ""

# ============================================================================
# STEP 1: Show Current Secret
# Display current secret values before making changes
# ============================================================================
echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}Step 1: Current Secret Values${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

"$UPDATE_SCRIPT" --read "$NAMESPACE" "$SECRET_NAME" "$KEY_NAME"

echo ""
read -p "Press Enter to continue to secret update..."
echo ""

# ============================================================================
# STEP 2: Update Secret
# Call lib/update-k8s-secret.sh with user-provided values
# ============================================================================
echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}Step 2: Update Secret${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

# Build arguments for the update script
UPDATE_ARGS=()
if [ "$DRY_RUN" == true ]; then
    UPDATE_ARGS+=("--dry-run")
fi

UPDATE_ARGS+=(
    "--merge"
    "$NAMESPACE"
    "$SECRET_NAME"
    "$KEY_NAME"
    "${KEY_VALUE_PAIRS[@]}"
)

# Execute the Kubernetes secret update
"$UPDATE_SCRIPT" "${UPDATE_ARGS[@]}"

UPDATE_EXIT_CODE=$?

if [ $UPDATE_EXIT_CODE -ne 0 ]; then
    echo -e "${RED}✗ Failed to update secret${NC}"
    exit $UPDATE_EXIT_CODE
fi

echo ""

if [ "$DRY_RUN" == true ]; then
    echo -e "${YELLOW}DRY-RUN: Secret update shown above (not applied)${NC}"
    echo ""
fi

# ============================================================================
# STEP 3: Restart Deployments (if not skipped)
# Call lib/restart-deployments.sh to cycle pods with new secrets
# ============================================================================
if [ "$SKIP_RESTART" == false ] && [ "$DRY_RUN" == false ]; then
    read -p "Press Enter to continue to deployment restart..."
    echo ""

    echo -e "${BLUE}======================================================================${NC}"
    echo -e "${BLUE}Step 3: Restart Deployments${NC}"
    echo -e "${BLUE}======================================================================${NC}"
    echo ""

    # Build arguments for the restart script
    RESTART_ARGS=()
    if [ "$SKIP_WAIT" == true ]; then
        RESTART_ARGS+=("--skip-wait")
    fi
    RESTART_ARGS+=("$NAMESPACE")

    # Execute the deployment restart
    "$RESTART_SCRIPT" "${RESTART_ARGS[@]}"

    RESTART_EXIT_CODE=$?

    if [ $RESTART_EXIT_CODE -ne 0 ]; then
        echo -e "${RED}✗ Failed to restart deployments${NC}"
        exit $RESTART_EXIT_CODE
    fi
else
    echo -e "${YELLOW}Skipping deployment restart (--skip-restart flag)${NC}"
fi

# ============================================================================
# SUMMARY
# Display final status and next steps
# ============================================================================
echo ""
echo -e "${GREEN}======================================================================${NC}"
if [ "$DRY_RUN" == true ]; then
    echo -e "${GREEN}Dry-run completed - No changes were made${NC}"
    echo -e "${GREEN}Remove --dry-run flag to execute${NC}"
else
    echo -e "${GREEN}✓ Secret rotation and deployment restart completed successfully!${NC}"
fi
echo -e "${GREEN}======================================================================${NC}"
echo ""

if [ "$DRY_RUN" == false ]; then
    echo "Summary:"
    echo "  ✓ Secret '$SECRET_NAME' updated in namespace '$NAMESPACE'"
    if [ "$SKIP_RESTART" == false ]; then
        echo "  ✓ Deployments restarted with new secret values"
    fi
    echo ""
    echo "Next steps:"
    echo "  - Verify applications are working correctly"
    echo "  - Check logs if needed: kubectl logs -n $NAMESPACE <pod-name>"
fi
