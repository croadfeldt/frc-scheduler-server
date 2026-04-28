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

# Wait for the POSTGRES_DB database to accept queries.
# pg_isready returns true as soon as postgres accepts connections — before
# initdb has finished creating POSTGRES_DB. This checks the actual database.
wait_for_postgres_db() {
  local pg_user="$1"
  local pg_db="$2"
  echo "    Waiting for database '$pg_db' to be ready..."
  for i in $(seq 1 36); do
    if oc exec -n "$NAMESPACE" deployment/frc-postgres -- \
        psql -U "$pg_user" -d "$pg_db" -c "SELECT 1" -q --no-align -t \
        > /dev/null 2>&1; then
      echo "    Database '$pg_db' is ready."
      return 0
    fi
    echo "    attempt $i/36 — waiting 5s..."
    sleep 5
  done
  echo "ERROR: Database '$pg_db' did not become ready after 3 minutes."
  oc logs -n "$NAMESPACE" deployment/frc-postgres --tail=30 2>/dev/null || true
  return 1
}

# Generate and apply the db secret with DATABASE_URL built from components.
# This avoids both shell quoting issues and the Kubernetes $(VAR) interpolation
# limitation with valueFrom: secretKeyRef sources.
apply_db_secret() {
  local ns="$1"
  local pg_user pg_pass pg_db

  # Read values from the already-applied secret if it exists, else error.
  pg_user=$(oc get secret frc-db-secret -n "$ns" \
    -o jsonpath='{.data.POSTGRES_USER}' 2>/dev/null | base64 -d) || true
  pg_pass=$(oc get secret frc-db-secret -n "$ns" \
    -o jsonpath='{.data.POSTGRES_PASSWORD}' 2>/dev/null | base64 -d) || true
  pg_db=$(oc get secret frc-db-secret -n "$ns" \
    -o jsonpath='{.data.POSTGRES_DB}' 2>/dev/null | base64 -d) || true

  if [ -z "$pg_user" ] || [ -z "$pg_pass" ] || [ -z "$pg_db" ]; then
    echo "ERROR: frc-db-secret not found or incomplete. Apply 01-secrets.yaml first."
    return 1
  fi

  # Write DATABASE_URL back into the secret using oc create/apply with --dry-run
  # piped to oc apply — this correctly handles all special characters.
  oc create secret generic frc-db-secret \
    --namespace="$ns" \
    --from-literal="POSTGRES_USER=${pg_user}" \
    --from-literal="POSTGRES_PASSWORD=${pg_pass}" \
    --from-literal="POSTGRES_DB=${pg_db}" \
    --from-literal="DATABASE_URL=postgresql+asyncpg://${pg_user}:${pg_pass}@frc-postgres:5432/${pg_db}" \
    --dry-run=client -o yaml | oc apply -f -

  echo "    DATABASE_URL set in frc-db-secret (db: ${pg_db}, user: ${pg_user})"
}
