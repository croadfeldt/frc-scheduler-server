#!/bin/bash
# Apply all vLLM vision-endpoint manifests in order.
#
# Pre-requisites (do these before running):
#   1. Label the GPU node:
#        oc label node <gpu-node-name> gpu-tier.example.com/role=vllm-vision
#   2. (Optional) for AMD/ROCm hardware, edit 02-deployment.yaml per
#      the comments in that file.
#
# The PVC uses the cluster's default StorageClass — no editing needed
# unless your cluster has no default. Run `oc get storageclass` to check.
set -euo pipefail

cd "$(dirname "$0")"

echo "Applying namespace…"
oc apply -f 00-namespace.yaml

echo "Applying PVC…"
oc apply -f 01-pvc.yaml

echo "Applying deployment…"
oc apply -f 02-deployment.yaml

echo "Applying service…"
oc apply -f 03-service.yaml

echo
echo "Done. Watch the pod start with:"
echo "  oc logs -n vllm-vision -f deploy/vllm-vision"
echo
echo "First start downloads ~9GB from Hugging Face — expect 5-15 minutes"
echo "before the endpoint is ready. Once you see 'Started server process'"
echo "in the logs, the endpoint is live at:"
echo "  http://vllm-vision.vllm-vision.svc.cluster.local:8000/v1"
echo
echo "If the PVC stays in Pending state, your cluster may not have a"
echo "default StorageClass set. Check with: oc get storageclass"
echo "Then edit 01-pvc.yaml to add 'storageClassName: <your-class>'"
