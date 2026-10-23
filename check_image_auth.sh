#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<EOF
Usage:
  Docker registry: $0 -r <registry> -u <username> [-p <password>] -f <images-file>
  AWS ECR:         $0 -E -a <access-key> [-s <secret-key>] [-R <region>] [-r <registry>] -f <images-file>

  -r  Registry host (or set REGISTRY). In ECR mode, derived from the AWS
      account and region if omitted.
  -u  Registry username    (or set REGISTRY_USERNAME)
  -p  Registry password    (or set REGISTRY_PASSWORD; prompted if omitted)
  -f  File listing images, one "repo:tag" per line (or set IMAGES_FILE).
      Blank lines and lines starting with # are ignored.

  AWS ECR options (requires the 'aws' CLI):
  -E  ECR mode. Also enabled automatically when -a is given.
  -a  AWS access key ID     (or set AWS_ACCESS_KEY_ID)
  -s  AWS secret access key (or set AWS_SECRET_ACCESS_KEY; prompted if omitted)
  -t  AWS session token     (or set AWS_SESSION_TOKEN; optional)
  -R  AWS region            (or set AWS_REGION / AWS_DEFAULT_REGION; default us-east-1)
  If -E is used without -a, the standard AWS credential chain (profile, env, role) is used.

Credentials are used to log crane in to the registry. They are stored in a
temporary docker config that is deleted on exit, so ~/.docker/config.json
is never modified.
EOF
  exit 1
}

REGISTRY="${REGISTRY:-}"
USERNAME="${REGISTRY_USERNAME:-}"
PASSWORD="${REGISTRY_PASSWORD:-}"
IMAGES_FILE="${IMAGES_FILE:-}"
ECR_MODE=false
AWS_KEY="${AWS_ACCESS_KEY_ID:-}"
AWS_SECRET="${AWS_SECRET_ACCESS_KEY:-}"
AWS_TOKEN="${AWS_SESSION_TOKEN:-}"
AWS_REGION_OPT="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"

while getopts "r:u:p:f:Ea:s:t:R:h" opt; do
  case "${opt}" in
    r) REGISTRY="${OPTARG}" ;;
    u) USERNAME="${OPTARG}" ;;
    p) PASSWORD="${OPTARG}" ;;
    f) IMAGES_FILE="${OPTARG}" ;;
    E) ECR_MODE=true ;;
    a) AWS_KEY="${OPTARG}"; ECR_MODE=true ;;
    s) AWS_SECRET="${OPTARG}" ;;
    t) AWS_TOKEN="${OPTARG}" ;;
    R) AWS_REGION_OPT="${OPTARG}" ;;
    *) usage ;;
  esac
done

[ -n "${IMAGES_FILE}" ] || { echo "[ERROR] Images file is required."; usage; }
[ -r "${IMAGES_FILE}" ] || { echo "[ERROR] Cannot read images file: ${IMAGES_FILE}"; exit 1; }

# Step 1: Check if crane is installed
if ! command -v crane &> /dev/null; then
  echo "[ERROR] 'crane' CLI tool is not installed or not in PATH."
  exit 1
fi

if [ "${ECR_MODE}" = true ]; then
  command -v aws &> /dev/null || { echo "[ERROR] 'aws' CLI tool is not installed or not in PATH."; exit 1; }

  if [ -n "${AWS_KEY}" ]; then
    if [ -z "${AWS_SECRET}" ]; then
      read -r -s -p "AWS secret access key for ${AWS_KEY}: " AWS_SECRET
      echo
    fi
    [ -n "${AWS_SECRET}" ] || { echo "[ERROR] AWS secret access key is required."; usage; }
    export AWS_ACCESS_KEY_ID="${AWS_KEY}" AWS_SECRET_ACCESS_KEY="${AWS_SECRET}"
    if [ -n "${AWS_TOKEN}" ]; then export AWS_SESSION_TOKEN="${AWS_TOKEN}"; else unset AWS_SESSION_TOKEN; fi
  fi
  unset AWS_KEY AWS_SECRET AWS_TOKEN
  export AWS_DEFAULT_REGION="${AWS_REGION_OPT:-${AWS_DEFAULT_REGION:-us-east-1}}"
  export AWS_PAGER=""

  if [ -z "${REGISTRY}" ]; then
    if ! ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>&1); then
      echo "[ERROR] Could not determine AWS account (invalid credentials?):"
      echo "${ACCOUNT_ID}"
      exit 1
    fi
    REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_DEFAULT_REGION}.amazonaws.com"
  fi

  if ! PASSWORD=$(aws ecr get-login-password --region "${AWS_DEFAULT_REGION}" 2>&1); then
    echo "[ERROR] aws ecr get-login-password failed:"
    echo "${PASSWORD}"
    exit 1
  fi
  USERNAME="AWS"
  # AWS creds stay exported: image checks use 'aws ecr batch-get-image'
  # (needs only ecr:BatchGetImage, not ecr:ListImages)
else
  [ -n "${REGISTRY}" ] || { echo "[ERROR] Registry is required."; usage; }
  [ -n "${USERNAME}" ] || { echo "[ERROR] Username is required."; usage; }
  # Prompt for the password (hidden) if it wasn't supplied
  if [ -z "${PASSWORD}" ]; then
    read -r -s -p "Password for ${USERNAME}@${REGISTRY}: " PASSWORD
    echo
  fi
  [ -n "${PASSWORD}" ] || { echo "[ERROR] Password is required."; usage; }
fi

# Isolated docker config + temp files, cleaned up on exit
WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT
export DOCKER_CONFIG="${WORKDIR}"
TAGS_FILE="${WORKDIR}/crane_tags.tmp"

echo "======================================================================"
echo "Authenticating to registry: ${REGISTRY} (user: ${USERNAME})"
echo "======================================================================"

# Step 2: Log crane in with the supplied credentials (password via stdin, not argv)
if ! LOGIN_ERR=$(printf '%s' "${PASSWORD}" | crane auth login "${REGISTRY}" -u "${USERNAME}" --password-stdin 2>&1); then
  echo "[ERROR] crane login failed for ${REGISTRY}:"
  echo "${LOGIN_ERR}"
  exit 1
fi
unset PASSWORD

# Step 3: Verify the credentials work against the registry.
# 'crane catalog' isn't supported by every registry, so a failure here is only a warning.
if [ "${ECR_MODE}" = true ]; then
  echo "[OK] ECR token obtained for ${REGISTRY} (images checked via batch-get-image)"
elif crane catalog "${REGISTRY}" &>/dev/null; then
  echo "[OK] Authenticated successfully to ${REGISTRY}"
else
  echo "[WARNING] Login saved, but the catalog check failed (some registries don't allow it)."
  echo "          Per-image results below will show whether credentials work."
fi

echo "Checking images against registry: ${REGISTRY}"
echo "----------------------------------------------------------------------"

# Load repository:tag pairs from the images file (skip blanks/comments, trim whitespace/CR)
declare -a IMAGES=()
while IFS= read -r line || [ -n "${line}" ]; do
  line="${line%%#*}"
  line="$(echo "${line}" | tr -d '' | xargs)"
  if [ -n "${line}" ]; then IMAGES+=("${line}"); fi
done < "${IMAGES_FILE}"

if [ "${#IMAGES[@]}" -eq 0 ]; then
  echo "[ERROR] No images found in ${IMAGES_FILE}"
  exit 1
fi
echo "Loaded ${#IMAGES[@]} images from ${IMAGES_FILE}"

# Iterate over each image and run crane ls
for item in "${IMAGES[@]}"; do
  REPO="${item%%:*}"
  TAG="${item#*:}"
  FULL_REPO="${REGISTRY}/${REPO}"

  if [ "${ECR_MODE}" = true ]; then
    # Registry host format: <account>.dkr.ecr.<region>.amazonaws.com
    ECR_ACCOUNT="${REGISTRY%%.*}"
    ECR_REGION="${REGISTRY#*.dkr.ecr.}"; ECR_REGION="${ECR_REGION%%.*}"
    if ECR_OUT=$(aws ecr batch-get-image --registry-id "${ECR_ACCOUNT}" --region "${ECR_REGION}" \
        --repository-name "${REPO}" --image-ids "imageTag=${TAG}" \
        --query 'length(images)' --output text 2>&1); then
      if [ "${ECR_OUT}" -ge 1 ] 2>/dev/null; then
        echo "[EXISTS]       ${FULL_REPO}:${TAG}"
      else
        echo "[NOT FOUND]    ${FULL_REPO}:${TAG}"
      fi
    elif echo "${ECR_OUT}" | grep -Ei "AccessDenied|not authorized|UnrecognizedClient|InvalidSignature|ExpiredToken" &>/dev/null; then
      echo "[AUTH FAILED]  ${FULL_REPO}:${TAG} (Authentication/Permission Error)"
    elif echo "${ECR_OUT}" | grep -Ei "RepositoryNotFound" &>/dev/null; then
      echo "[NOT FOUND]    ${FULL_REPO}:${TAG} (repository does not exist)"
    else
      echo "[ERROR]        ${FULL_REPO}:${TAG} (${ECR_OUT})"
    fi
    continue
  fi

  # Capture error output to distinguish between Auth Failure (401/403) and Tag Not Found
  ERR_OUTPUT=$(crane ls "${FULL_REPO}" 2>&1 >"${TAGS_FILE}" || true)

  if [ -s "${TAGS_FILE}" ] && grep -xqF "${TAG}" "${TAGS_FILE}"; then
    echo "[EXISTS]       ${FULL_REPO}:${TAG}"
  elif echo "${ERR_OUTPUT}" | grep -Ei "UNAUTHORIZED|DENIED|401|403" &>/dev/null; then
    echo "[AUTH FAILED]  ${FULL_REPO}:${TAG} (Authentication/Permission Error)"
  else
    echo "[NOT FOUND]    ${FULL_REPO}:${TAG}"
  fi

  : > "${TAGS_FILE}"
done
