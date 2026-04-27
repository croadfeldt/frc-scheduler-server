#!/bin/bash
# Apply all OpenShift manifests with config substitution.
# Can be run from anywhere:
#   ./openshift/apply.sh   (from repo root)
#   ./apply.sh             (from inside openshift/)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$SCRIPT_DIR/config.env"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: $CONFIG not found. Copy config.env.example and fill in your values."
  exit 1
fi

source "$CONFIG"

: "${NAMESPACE:?Set NAMESPACE in config.env}"
: "${APP_HOSTNAME:?Set APP_HOSTNAME in config.env}"
: "${GIT_REPO_URL:?Set GIT_REPO_URL in config.env}"
: "${CERT_ISSUER:?Set CERT_ISSUER in config.env}"

GIT_BRANCH="${GIT_BRANCH:-main}"
METALLB_IP="${METALLB_IP:-}"
K8S_SERVICE_CIDR="${K8S_SERVICE_CIDR:-172.30.0.0/16}"
APP_PORT="${APP_PORT:-8443}"
CPU_WORKERS="${CPU_WORKERS:-12}"
WEB_WORKERS="${WEB_WORKERS:-1}"

apply_manifest() {
  local file="$1"
  sed \
    -e "s|NAMESPACE_PLACEHOLDER|${NAMESPACE}|g" \
    -e "s|YOUR_HOSTNAME|${APP_HOSTNAME}|g" \
    -e "s|https://YOUR_HOSTNAME|https://${APP_HOSTNAME}|g" \
    -e "s|https://github.com/YOUR_ORG/YOUR_REPO.git|${GIT_REPO_URL}|g" \
    -e "s|GIT_BRANCH_PLACEHOLDER|${GIT_BRANCH}|g" \
    -e "s|letsencrypt-prod|${CERT_ISSUER}|g" \
    -e "s|METALLB_IP_PLACEHOLDER|${METALLB_IP}|g" \
    -e "s|K8S_SERVICE_CIDR_PLACEHOLDER|${K8S_SERVICE_CIDR}|g" \
    -e "s|APP_PORT_PLACEHOLDER|${APP_PORT}|g" \
    -e "s|CPU_WORKERS_PLACEHOLDER|${CPU_WORKERS}|g" \
    -e "s|WEB_WORKERS_PLACEHOLDER|${WEB_WORKERS}|g" \
    "$file" | oc apply -f -
}

echo "Applying manifests to namespace: ${NAMESPACE}"
for manifest in "$SCRIPT_DIR"/[0-9]*.yaml; do
  echo "  -> $(basename "$manifest")"
  apply_manifest "$manifest"
done

echo ""
echo "Done. Monitor build: oc start-build frc-scheduler-server-git --follow -n ${NAMESPACE}"
