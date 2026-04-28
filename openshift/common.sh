# common.sh — shared functions for apply.sh and rebuild.sh
# Sourced by both scripts, not executed directly.

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

# Verify that DATABASE_URL exists in frc-db-secret and contains the right db name.
# Exits with error if missing — the user must add it to 01-secrets.yaml.
check_db_secret() {
  local ns="$1"
  local db_url
  db_url=$(oc get secret frc-db-secret -n "$ns" \
    -o jsonpath='{.data.DATABASE_URL}' 2>/dev/null | base64 -d)

  if [ -z "$db_url" ]; then
    echo ""
    echo "ERROR: DATABASE_URL is missing from frc-db-secret."
    echo "Add it to your 01-secrets.yaml:"
    echo ""
    echo "  DATABASE_URL: \"postgresql+asyncpg://USER:PASS@frc-postgres:5432/DB\""
    echo ""
    echo "See openshift/01-secrets.yaml.example for the full template."
    return 1
  fi

  echo "    DATABASE_URL: ${db_url}"
}

# Wait for the POSTGRES_DB database to accept queries.
wait_for_postgres_db() {
  local ns="$1"
  local pg_user="$2"
  local pg_db="$3"
  echo "    Waiting for database '$pg_db' to be ready..."
  for i in $(seq 1 36); do
    if oc exec -n "$ns" deployment/frc-postgres --         pg_isready -h 127.0.0.1 -U "$pg_user" -d "$pg_db"         > /dev/null 2>&1; then
      echo "    Database '$pg_db' is ready."
      return 0
    fi
    echo "    attempt $i/36 — waiting 5s..."
    sleep 5
  done
  echo "ERROR: Database '$pg_db' did not become ready after 3 minutes."
  oc logs -n "$ns" deployment/frc-postgres --tail=30 2>/dev/null || true
  return 1
}

refresh_registry() {
  echo "    Refreshing image registry operator (NooBaa credential reconcile)..."
  oc patch configs.imageregistry.operator.openshift.io cluster \
    --type merge --patch '{"spec":{"managementState":"Removed"}}' 2>/dev/null || true
  sleep 15
  oc patch configs.imageregistry.operator.openshift.io cluster \
    --type merge --patch '{"spec":{"managementState":"Managed"}}' 2>/dev/null || true
  echo "    Waiting for registry rollout..."
  oc rollout status deployment/image-registry \
    -n openshift-image-registry --timeout=120s 2>/dev/null || true
  echo "    Registry ready."
}

link_builder_registry_secret() {
  local ns="$1"
  local secret
  secret=$(oc get secret -n "$ns" -o name 2>/dev/null \
    | grep builder-dockercfg | head -1 | sed 's|secret/||')
  if [ -n "$secret" ]; then
    oc secrets link builder "$secret" --for=mount -n "$ns" 2>/dev/null || true
    oc secrets link default  "$secret" --for=pull  -n "$ns" 2>/dev/null || true
    echo "    Linked registry secret $secret to builder/default SAs"
  fi
}
