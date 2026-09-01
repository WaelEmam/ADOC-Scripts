#!/bin/bash

# Wrapper script to rotate secrets and restart deployments
# Usage: ./rotate-secret-and-restart.sh [OPTIONS] <namespace> <secret-name> <key-name> <key=value pairs...>

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    echo "Usage: $0 [OPTIONS] <namespace> <secret-name> <key-name> <key=value pairs...>"
    echo ""
    echo "Options:"
    echo "  --dry-run          Preview all changes without applying them"
    echo "  --skip-restart     Update secret but don't restart deployments"
    echo "  --skip-wait        Don't wait for pods to be ready after restart"
    echo "  -h, --help         Show this help message"
    echo ""
    echo "Description:"
    echo "  Complete workflow to rotate Kubernetes secrets and restart affected deployments:"
    echo "  1. Shows current secret values"
    echo "  2. Updates secret with new values (merge mode)"
    echo "  3. Restarts deployments to pick up new secret values"
    echo ""
    echo "Examples:"
    echo "  # Dry-run to preview all changes"
    echo "  $0 --dry-run partnerusdcdpv2 global-storage globalstorage.json \\"
    echo "    'MEASURE_RESULT_FS_S3A_ACCESS_KEY=newkey' \\"
    echo "    'MEASURE_RESULT_FS_S3A_SECRET_KEY=newsecret'"
    echo ""
    echo "  # Execute the full rotation"
    echo "  $0 partnerusdcdpv2 global-storage globalstorage.json \\"
    echo "    'MEASURE_RESULT_FS_S3A_ACCESS_KEY=newkey' \\"
    echo "    'MEASURE_RESULT_FS_S3A_SECRET_KEY=newsecret'"
    echo ""
    echo "  # Update secret only, skip restart"
    echo "  $0 --skip-restart partnerusdcdpv2 global-storage globalstorage.json \\"
    echo "    'MEASURE_RESULT_FS_S3A_ACCESS_KEY=newkey'"
    exit 1
}

# Parse options
DRY_RUN=false
SKIP_RESTART=false
SKIP_WAIT=false

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

# Remaining arguments
NAMESPACE=$1
SECRET_NAME=$2
KEY_NAME=$3
shift 3 2>/dev/null || true
KEY_VALUE_PAIRS=("$@")

# Validate arguments
if [ -z "$NAMESPACE" ] || [ -z "$SECRET_NAME" ] || [ -z "$KEY_NAME" ] || [ ${#KEY_VALUE_PAIRS[@]} -eq 0 ]; then
    echo -e "${RED}Error: Missing required arguments${NC}"
    usage
fi

# Check if required scripts exist
UPDATE_SCRIPT="$SCRIPT_DIR/update-k8s-secret.sh"
RESTART_SCRIPT="$SCRIPT_DIR/restart-deployments.sh"

if [ ! -f "$UPDATE_SCRIPT" ]; then
    echo -e "${RED}Error: update-k8s-secret.sh not found in $SCRIPT_DIR${NC}"
    exit 1
fi

if [ ! -f "$RESTART_SCRIPT" ]; then
    echo -e "${RED}Error: restart-deployments.sh not found in $SCRIPT_DIR${NC}"
    exit 1
fi

echo -e "${CYAN}======================================================================${NC}"
echo -e "${CYAN}Secret Rotation and Deployment Restart Workflow${NC}"
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
# STEP 1: Show current secret
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
# STEP 2: Update secret
# ============================================================================
echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}Step 2: Update Secret${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

if [ "$DRY_RUN" == true ]; then
    "$UPDATE_SCRIPT" --merge --dry-run "$NAMESPACE" "$SECRET_NAME" "$KEY_NAME" "${KEY_VALUE_PAIRS[@]}"
else
    "$UPDATE_SCRIPT" --merge "$NAMESPACE" "$SECRET_NAME" "$KEY_NAME" "${KEY_VALUE_PAIRS[@]}"
fi

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Failed to update secret${NC}"
    exit 1
fi

echo ""

if [ "$DRY_RUN" == true ]; then
    echo -e "${YELLOW}DRY-RUN: Secret update shown above (not applied)${NC}"
    echo ""
fi

# ============================================================================
# STEP 3: Restart deployments
# ============================================================================
if [ "$SKIP_RESTART" == false ]; then
    if [ "$DRY_RUN" == false ]; then
        read -p "Press Enter to continue to deployment restart..."
        echo ""
    fi

    echo -e "${BLUE}======================================================================${NC}"
    echo -e "${BLUE}Step 3: Restart Deployments${NC}"
    echo -e "${BLUE}======================================================================${NC}"
    echo ""

    RESTART_ARGS=()
    if [ "$DRY_RUN" == true ]; then
        RESTART_ARGS+=("--dry-run")
    fi
    if [ "$SKIP_WAIT" == true ]; then
        RESTART_ARGS+=("--skip-wait")
    fi

    "$RESTART_SCRIPT" "${RESTART_ARGS[@]}" "$NAMESPACE"

    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Failed to restart deployments${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}Skipping deployment restart (--skip-restart flag)${NC}"
fi

# ============================================================================
# SUMMARY
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
