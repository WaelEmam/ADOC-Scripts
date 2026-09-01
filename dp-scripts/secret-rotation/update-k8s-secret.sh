#!/bin/bash

# Script to read, merge, or update a Kubernetes secret with base64-encoded values
# Usage: ./update-k8s-secret.sh [OPTIONS] <namespace> <secret-name> <key-name> [data]

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
    echo "Usage: $0 [OPTIONS] <namespace> <secret-name> <key-name> [data]"
    echo ""
    echo "Modes:"
    echo "  --read           Read and display the current secret value (decoded)"
    echo "  --merge          Merge specific fields into existing JSON (default for key=value format)"
    echo "  --replace        Replace entire secret content with new JSON"
    echo ""
    echo "Options:"
    echo "  --dry-run        Show what would change without applying the update"
    echo "  --no-backup      Skip creating a backup file (not recommended)"
    echo ""
    echo "Arguments:"
    echo "  namespace        Kubernetes namespace containing the secret"
    echo "  secret-name      Name of the existing Kubernetes secret"
    echo "  key-name         Key within the secret to read/update"
    echo "  data             JSON string, @file, or key=value pairs for merge"
    echo ""
    echo "Examples:"
    echo ""
    echo "  # Read existing secret:"
    echo "  $0 --read default my-secret config"
    echo ""
    echo "  # Merge specific fields (preserves other fields):"
    echo "  $0 --merge default my-secret config 'ACCESS_KEY=newkey' 'SECRET_KEY=newsecret'"
    echo ""
    echo "  # Dry-run to preview changes:"
    echo "  $0 --merge --dry-run default my-secret config 'ACCESS_KEY=newkey'"
    echo ""
    echo "  # Replace entire content:"
    echo "  $0 --replace default my-secret config '{\"key\":\"value\"}'"
    echo ""
    echo "  # Replace from file:"
    echo "  $0 --replace default my-secret config @/path/to/config.json"
    echo ""
    echo "  # List all keys in a secret:"
    echo "  $0 --read default my-secret"
    exit 1
}

# Parse command line arguments
READ_MODE=false
MERGE_MODE=false
REPLACE_MODE=false
DRY_RUN=false
NO_BACKUP=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --read)
            READ_MODE=true
            shift
            ;;
        --merge)
            MERGE_MODE=true
            shift
            ;;
        --replace)
            REPLACE_MODE=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --no-backup)
            NO_BACKUP=true
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
KEY_NAME=${3:-""}
shift 3 2>/dev/null || true
DATA_ARGS=("$@")

# Validate arguments
if [ -z "$NAMESPACE" ] || [ -z "$SECRET_NAME" ]; then
    echo -e "${RED}Error: Missing required arguments${NC}"
    usage
fi

# Check if required tools are available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed or not in PATH${NC}"
    exit 1
fi

if ! command -v jq &> /dev/null; then
    echo -e "${RED}Error: jq is not installed or not in PATH${NC}"
    echo -e "${YELLOW}Install jq: brew install jq (macOS) or apt-get install jq (Linux)${NC}"
    exit 1
fi

# Check if secret exists
echo -e "${YELLOW}Checking if secret exists...${NC}"
if ! kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" &> /dev/null; then
    echo -e "${RED}Error: Secret '$SECRET_NAME' not found in namespace '$NAMESPACE'${NC}"
    exit 1
fi

# ============================================================================
# READ MODE: Display the current secret value
# ============================================================================
if [ "$READ_MODE" == true ]; then
    echo -e "${BLUE}Reading secret '$SECRET_NAME' from namespace '$NAMESPACE'${NC}"
    echo ""

    if [ -z "$KEY_NAME" ]; then
        # Read all keys in the secret
        echo -e "${GREEN}All keys in secret:${NC}"
        kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o json | jq -r '.data | keys[]'
        echo ""
        echo -e "${YELLOW}To read a specific key, run:${NC}"
        echo "$0 --read $NAMESPACE $SECRET_NAME <key-name>"
    else
        # Read specific key
        SECRET_VALUE=$(kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o json | jq -r --arg key "$KEY_NAME" '.data[$key] // empty' 2>/dev/null)

        if [ -z "$SECRET_VALUE" ]; then
            echo -e "${RED}Error: Key '$KEY_NAME' not found in secret '$SECRET_NAME'${NC}"
            echo ""
            echo -e "${YELLOW}Available keys:${NC}"
            kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o json | jq -r '.data | keys[]'
            exit 1
        fi

        # Decode the secret
        DECODED_VALUE=$(echo "$SECRET_VALUE" | base64 -d)

        echo -e "${GREEN}Key: $KEY_NAME${NC}"
        echo -e "${GREEN}Decoded value:${NC}"
        echo ""

        # Try to pretty-print if it's JSON
        if echo "$DECODED_VALUE" | jq . &> /dev/null; then
            echo "$DECODED_VALUE" | jq .
        else
            echo "$DECODED_VALUE"
        fi

        echo ""
        echo -e "${BLUE}Base64 encoded value:${NC}"
        echo "$SECRET_VALUE"
    fi

    exit 0
fi

# ============================================================================
# UPDATE/MERGE MODE: Update the secret
# ============================================================================

if [ -z "$KEY_NAME" ]; then
    echo -e "${RED}Error: key-name is required for update operations${NC}"
    usage
fi

if [ ${#DATA_ARGS[@]} -eq 0 ]; then
    echo -e "${RED}Error: No data provided for update${NC}"
    usage
fi

# Determine mode automatically if not specified
if [ "$MERGE_MODE" == false ] && [ "$REPLACE_MODE" == false ]; then
    # Auto-detect: if first arg looks like key=value, use merge mode
    if [[ "${DATA_ARGS[0]}" == *"="* ]]; then
        MERGE_MODE=true
    else
        REPLACE_MODE=true
    fi
fi

# Read existing secret value
EXISTING_SECRET=$(kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o json | jq -r --arg key "$KEY_NAME" '.data[$key] // empty' 2>/dev/null)

if [ -z "$EXISTING_SECRET" ]; then
    echo -e "${RED}Error: Key '$KEY_NAME' not found in secret '$SECRET_NAME'${NC}"
    echo ""
    echo -e "${YELLOW}Available keys:${NC}"
    kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o json | jq -r '.data | keys[]'
    exit 1
fi

EXISTING_JSON=$(echo "$EXISTING_SECRET" | base64 -d)

# Validate existing content is JSON
if ! echo "$EXISTING_JSON" | jq . &> /dev/null; then
    echo -e "${RED}Error: Existing secret value is not valid JSON${NC}"
    echo "Cannot merge into non-JSON content. Use --replace mode instead."
    exit 1
fi

# ============================================================================
# MERGE MODE: Update specific fields
# ============================================================================
if [ "$MERGE_MODE" == true ]; then
    echo -e "${CYAN}Merge mode: Updating specific fields in existing JSON${NC}"
    echo ""

    # Parse key=value pairs
    NEW_JSON="$EXISTING_JSON"

    for arg in "${DATA_ARGS[@]}"; do
        if [[ "$arg" == *"="* ]]; then
            KEY="${arg%%=*}"
            VALUE="${arg#*=}"
            echo -e "${YELLOW}Setting $KEY = $VALUE${NC}"
            NEW_JSON=$(echo "$NEW_JSON" | jq --arg key "$KEY" --arg val "$VALUE" '.[$key] = $val')
        else
            echo -e "${RED}Error: Invalid format '$arg'. Expected key=value${NC}"
            exit 1
        fi
    done

    JSON_CONTENT="$NEW_JSON"

# ============================================================================
# REPLACE MODE: Replace entire content
# ============================================================================
elif [ "$REPLACE_MODE" == true ]; then
    echo -e "${CYAN}Replace mode: Replacing entire secret content${NC}"
    echo ""

    DATA="${DATA_ARGS[0]}"

    # Handle JSON data from file or string
    if [[ "$DATA" == @* ]]; then
        # Remove @ prefix and read from file
        JSON_FILE="${DATA:1}"
        if [ ! -f "$JSON_FILE" ]; then
            echo -e "${RED}Error: File '$JSON_FILE' not found${NC}"
            exit 1
        fi
        echo -e "${YELLOW}Reading JSON from file: $JSON_FILE${NC}"
        JSON_CONTENT=$(cat "$JSON_FILE")
    else
        JSON_CONTENT="$DATA"
    fi

    # Validate JSON format
    if ! echo "$JSON_CONTENT" | jq . &> /dev/null; then
        echo -e "${RED}Error: Invalid JSON format${NC}"
        exit 1
    fi
fi

# ============================================================================
# COMPARE EXISTING vs NEW
# ============================================================================
echo ""
echo -e "${YELLOW}Comparing existing secret with new values...${NC}"

# Normalize JSON for comparison (sorted keys, compact)
EXISTING_JSON_NORMALIZED=$(echo "$EXISTING_JSON" | jq -S -c .)
NEW_JSON_NORMALIZED=$(echo "$JSON_CONTENT" | jq -S -c .)

if [ "$EXISTING_JSON_NORMALIZED" == "$NEW_JSON_NORMALIZED" ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✓ No changes detected${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "The new values match the existing secret exactly."
    echo "No update is necessary."
    echo ""
    echo "Details:"
    echo "  Namespace: $NAMESPACE"
    echo "  Secret: $SECRET_NAME"
    echo "  Key: $KEY_NAME"
    echo ""

    if [ "$DRY_RUN" == false ]; then
        echo -e "${CYAN}Tip: The secret already contains the provided values.${NC}"
    fi

    exit 0
fi

echo -e "${CYAN}✓ Changes detected - proceeding with update${NC}"
echo ""

# ============================================================================
# SHOW DIFF
# ============================================================================
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Changes to be applied:${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

echo -e "${RED}BEFORE:${NC}"
echo "$EXISTING_JSON" | jq .
echo ""

echo -e "${GREEN}AFTER:${NC}"
echo "$JSON_CONTENT" | jq .
echo ""

echo -e "${CYAN}DIFF:${NC}"
diff -u <(echo "$EXISTING_JSON" | jq -S .) <(echo "$JSON_CONTENT" | jq -S .) || true
echo ""

# Encode to base64
BASE64_ENCODED=$(echo -n "$JSON_CONTENT" | base64)

# ============================================================================
# DRY RUN MODE
# ============================================================================
if [ "$DRY_RUN" == true ]; then
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}DRY RUN MODE - No changes applied${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    echo "Namespace: $NAMESPACE"
    echo "Secret: $SECRET_NAME"
    echo "Key: $KEY_NAME"
    echo ""
    echo -e "${GREEN}New base64 value:${NC}"
    echo "$BASE64_ENCODED"
    echo ""
    echo -e "${YELLOW}To apply these changes, remove --dry-run flag${NC}"
    exit 0
fi

# ============================================================================
# APPLY CHANGES
# ============================================================================

# Create a backup of the current secret
if [ "$NO_BACKUP" == false ]; then
    echo -e "${YELLOW}Creating backup of current secret...${NC}"
    BACKUP_FILE="/tmp/${NAMESPACE}-${SECRET_NAME}-backup-$(date +%Y%m%d-%H%M%S).yaml"
    kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o yaml > "$BACKUP_FILE"
    echo -e "${GREEN}Backup saved to: $BACKUP_FILE${NC}"
    echo ""
fi

# Update the secret (escape special characters in JSON path)
echo -e "${YELLOW}Updating secret '$SECRET_NAME' in namespace '$NAMESPACE'...${NC}"

# Escape forward slashes and tildes in key name for JSON Patch (RFC 6901)
ESCAPED_KEY=$(echo "$KEY_NAME" | sed 's/~/~0/g' | sed 's/\//~1/g')

kubectl patch secret "$SECRET_NAME" -n "$NAMESPACE" \
    --type='json' \
    -p="[{\"op\": \"replace\", \"path\": \"/data/$ESCAPED_KEY\", \"value\": \"$BASE64_ENCODED\"}]"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Secret updated successfully!${NC}"
    echo ""
    echo "Details:"
    echo "  Namespace: $NAMESPACE"
    echo "  Secret: $SECRET_NAME"
    echo "  Key: $KEY_NAME"
    if [ "$NO_BACKUP" == false ]; then
        echo "  Backup: $BACKUP_FILE"
    fi

    # Verify the update
    echo ""
    echo -e "${YELLOW}Verifying update...${NC}"
    CURRENT_VALUE=$(kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o json | jq -r --arg key "$KEY_NAME" '.data[$key]' | base64 -d)
    if [ "$CURRENT_VALUE" == "$JSON_CONTENT" ]; then
        echo -e "${GREEN}✓ Verification successful - secret matches input${NC}"
    else
        echo -e "${RED}⚠ Warning: Verification failed - secret may not match input${NC}"
    fi
else
    echo -e "${RED}✗ Failed to update secret${NC}"
    exit 1
fi
