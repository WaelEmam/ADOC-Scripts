#!/bin/bash

# Script to scale down and up Kubernetes deployments (useful after secret rotation)
# Usage: ./restart-deployments.sh [OPTIONS] <namespace>

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Function to display usage
usage() {
    echo "Usage: $0 [OPTIONS] <namespace>"
    echo ""
    echo "Options:"
    echo "  --dry-run          Show what would happen without executing"
    echo "  --wait-timeout     Timeout in seconds for waiting (default: 300)"
    echo "  --skip-wait        Don't wait for pods to be ready"
    echo "  -h, --help         Show this help message"
    echo ""
    echo "Description:"
    echo "  Scales down specified deployments to 0 replicas, then scales them back up"
    echo "  to their target replica counts. Useful after rotating secrets/configmaps."
    echo ""
    echo "Example:"
    echo "  # Dry-run to preview actions"
    echo "  $0 --dry-run partnerusdcdpv2"
    echo ""
    echo "  # Execute the restart"
    echo "  $0 partnerusdcdpv2"
    echo ""
    echo "  # Skip waiting for pods to be ready"
    echo "  $0 --skip-wait partnerusdcdpv2"
    exit 1
}

# Deployment configurations: deployment_name:target_replicas
# Format: "deployment_name:replicas"
DEPLOYMENTS=(
    "acceldata-dataplane-analysis-service:1"
    "acceldata-dataplane-analysis-standalone-service:1"
    "sparkoperator:1"
    "acceldata-dataplane-torch-monitor-service:2"
)

# Function to get deployment name from entry
get_deployment_name() {
    echo "${1%%:*}"
}

# Function to get target replicas from entry
get_target_replicas() {
    echo "${1##*:}"
}

# Parse command line arguments
DRY_RUN=false
WAIT_TIMEOUT=300
SKIP_WAIT=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --wait-timeout)
            WAIT_TIMEOUT=$2
            shift 2
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

NAMESPACE=$1

if [ -z "$NAMESPACE" ]; then
    echo -e "${RED}Error: Namespace is required${NC}"
    usage
fi

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed or not in PATH${NC}"
    exit 1
fi

# Check if namespace exists
if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
    echo -e "${RED}Error: Namespace '$NAMESPACE' not found${NC}"
    exit 1
fi

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}Deployment Restart Plan${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
echo "Namespace: $NAMESPACE"
echo "Mode: $([ "$DRY_RUN" == true ] && echo 'DRY-RUN' || echo 'EXECUTE')"
echo ""

# Verify deployments exist and show current state
echo -e "${YELLOW}Checking deployment status...${NC}"
echo ""

MISSING_DEPLOYMENTS=()
for ENTRY in "${DEPLOYMENTS[@]}"; do
    DEPLOYMENT=$(get_deployment_name "$ENTRY")
    TARGET_REPLICAS=$(get_target_replicas "$ENTRY")

    if ! kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" &> /dev/null; then
        echo -e "${RED}✗ $DEPLOYMENT - NOT FOUND${NC}"
        MISSING_DEPLOYMENTS+=("$DEPLOYMENT")
    else
        CURRENT_REPLICAS=$(kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.status.replicas}' 2>/dev/null || echo "0")
        READY_REPLICAS=$(kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        echo -e "${GREEN}✓ $DEPLOYMENT${NC}"
        echo "  Current: $CURRENT_REPLICAS replica(s) ($READY_REPLICAS ready)"
        echo "  Target:  $TARGET_REPLICAS replica(s)"
        echo ""
    fi
done

if [ ${#MISSING_DEPLOYMENTS[@]} -gt 0 ]; then
    echo -e "${RED}Error: ${#MISSING_DEPLOYMENTS[@]} deployment(s) not found in namespace '$NAMESPACE'${NC}"
    exit 1
fi

if [ "$DRY_RUN" == true ]; then
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}DRY RUN MODE - No changes will be made${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    echo "Would execute:"
    echo "1. Scale down all deployments to 0 replicas"
    echo "2. Wait for all pods to terminate"
    echo "3. Scale up deployments to target replicas"
    echo "4. Wait for all pods to be ready"
    echo ""
    echo "To execute, remove --dry-run flag"
    exit 0
fi

# ============================================================================
# SCALE DOWN
# ============================================================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Step 1: Scaling down deployments${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

for ENTRY in "${DEPLOYMENTS[@]}"; do
    DEPLOYMENT=$(get_deployment_name "$ENTRY")
    echo -e "${YELLOW}Scaling down $DEPLOYMENT to 0 replicas...${NC}"
    kubectl scale deployment "$DEPLOYMENT" -n "$NAMESPACE" --replicas=0
    echo -e "${GREEN}✓ Scaled down $DEPLOYMENT${NC}"
    echo ""
done

# Wait for all pods to terminate
if [ "$SKIP_WAIT" == false ]; then
    echo -e "${YELLOW}Waiting for all pods to terminate...${NC}"
    WAIT_START=$(date +%s)

    while true; do
        ALL_TERMINATED=true

        for ENTRY in "${DEPLOYMENTS[@]}"; do
            DEPLOYMENT=$(get_deployment_name "$ENTRY")
            POD_COUNT=$(kubectl get pods -n "$NAMESPACE" -l "app.kubernetes.io/name=${DEPLOYMENT}" --field-selector=status.phase!=Terminating 2>/dev/null | grep -v NAME | wc -l || echo "0")

            if [ "$POD_COUNT" -gt 0 ]; then
                ALL_TERMINATED=false
                break
            fi
        done

        if [ "$ALL_TERMINATED" == true ]; then
            echo -e "${GREEN}✓ All pods terminated${NC}"
            break
        fi

        ELAPSED=$(($(date +%s) - WAIT_START))
        if [ $ELAPSED -ge $WAIT_TIMEOUT ]; then
            echo -e "${RED}✗ Timeout waiting for pods to terminate${NC}"
            exit 1
        fi

        echo -n "."
        sleep 2
    done
    echo ""
fi

echo ""

# ============================================================================
# SCALE UP
# ============================================================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Step 2: Scaling up deployments${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

for ENTRY in "${DEPLOYMENTS[@]}"; do
    DEPLOYMENT=$(get_deployment_name "$ENTRY")
    TARGET_REPLICAS=$(get_target_replicas "$ENTRY")
    echo -e "${YELLOW}Scaling up $DEPLOYMENT to $TARGET_REPLICAS replica(s)...${NC}"
    kubectl scale deployment "$DEPLOYMENT" -n "$NAMESPACE" --replicas="$TARGET_REPLICAS"
    echo -e "${GREEN}✓ Scaled up $DEPLOYMENT${NC}"
    echo ""
done

# Wait for all pods to be ready
if [ "$SKIP_WAIT" == false ]; then
    echo -e "${YELLOW}Waiting for all pods to be ready...${NC}"
    WAIT_START=$(date +%s)

    for ENTRY in "${DEPLOYMENTS[@]}"; do
        DEPLOYMENT=$(get_deployment_name "$ENTRY")
        TARGET_REPLICAS=$(get_target_replicas "$ENTRY")
        echo -e "${CYAN}Waiting for $DEPLOYMENT ($TARGET_REPLICAS replica(s))...${NC}"

        if ! kubectl rollout status deployment "$DEPLOYMENT" -n "$NAMESPACE" --timeout="${WAIT_TIMEOUT}s"; then
            echo -e "${RED}✗ Timeout waiting for $DEPLOYMENT${NC}"
            exit 1
        fi

        echo -e "${GREEN}✓ $DEPLOYMENT is ready${NC}"
        echo ""
    done
fi

# ============================================================================
# SUMMARY
# ============================================================================
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ All deployments restarted successfully${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

echo "Final status:"
echo ""

for ENTRY in "${DEPLOYMENTS[@]}"; do
    DEPLOYMENT=$(get_deployment_name "$ENTRY")
    TARGET_REPLICAS=$(get_target_replicas "$ENTRY")
    CURRENT_REPLICAS=$(kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.status.replicas}' 2>/dev/null || echo "0")
    READY_REPLICAS=$(kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    AVAILABLE_REPLICAS=$(kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo "0")

    if [ "$READY_REPLICAS" == "$TARGET_REPLICAS" ] && [ "$AVAILABLE_REPLICAS" == "$TARGET_REPLICAS" ]; then
        echo -e "${GREEN}✓ $DEPLOYMENT: $READY_REPLICAS/$TARGET_REPLICAS ready${NC}"
    else
        echo -e "${YELLOW}⚠ $DEPLOYMENT: $READY_REPLICAS/$TARGET_REPLICAS ready${NC}"
    fi
done

echo ""
echo -e "${CYAN}Pods with new secrets are now running${NC}"
