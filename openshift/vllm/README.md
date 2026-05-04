# vLLM vision endpoint for PDF schedule import

This directory contains OpenShift manifests for deploying a self-hosted
vision-capable LLM that the FRC scheduler uses to parse arbitrary
schedule PDFs (image-based PDFs, scanned schedules, MSHSL state, etc.).

The model is **Qwen2.5-VL-7B-Instruct-AWQ** — a 7-billion-parameter
vision-language model from Alibaba's Qwen team, AWQ-quantized to ~9GB.
Apache 2.0 licensed, not gated on Hugging Face.

The vLLM server exposes an OpenAI-compatible API at `/v1`. The scheduler
sends rasterized PDF page images via `image_url` content blocks and gets
back structured JSON.

## Why a separate namespace and deployment?

This is reusable inference infrastructure. Other services (current or
future) might want vision capabilities too. Keeping it in its own
namespace makes it easy to:

- Restart or upgrade the inference layer without touching the scheduler
- Add a Route + auth later if exposed externally
- Scale or relocate to different hardware
- Reuse for non-FRC workloads

## Hardware requirements

- **One GPU with ≥10GB VRAM**. The AWQ-quantized model loads to ~9GB;
  vLLM's KV cache adds a few GB on top. A 16GB GPU has comfortable
  headroom; 12GB cards work but with reduced max sequence length.
- **NVIDIA (CUDA) or AMD (ROCm)**. The default manifest assumes NVIDIA
  with the GPU operator installed. For AMD, see the AMD section below.
- **PVC for model cache** — ~10GB. The model downloads on first start
  (~9GB pulled from Hugging Face). Without persistent storage, every
  pod restart re-downloads.

## Files

- `00-namespace.yaml`   — namespace `vllm-vision`
- `01-pvc.yaml`          — PVC for model cache (10Gi)
- `02-deployment.yaml`   — vLLM deployment (NVIDIA default; AMD comment block included)
- `03-service.yaml`      — internal `ClusterIP` service on port 8000
- `apply.sh`             — convenience script to apply all manifests in order

## Setup

### 1. Pick a node and label it

The vLLM pod needs to land on the node with a free GPU. The deployment
uses a `nodeSelector` matching `gpu-tier.example.com/role: vllm-vision`.
Apply that label to your chosen node:

```sh
oc label node <gpu-node-name> gpu-tier.example.com/role=vllm-vision --overwrite
```

If you prefer a different label key, edit `02-deployment.yaml` to match.
Kubernetes label keys with a `/` need a domain-style prefix; pick any
domain you control or use the `example.com` placeholder shown.

You can verify the node is labeled:

```sh
oc get nodes -l gpu-tier.example.com/role=vllm-vision
```

### 2. Storage class (usually no action needed)

The PVC defined in `01-pvc.yaml` uses the cluster's default StorageClass.
On most OpenShift clusters this works out of the box — apply.sh will
create the PVC and the cluster's default class will provision the
volume.

If your cluster has no default class, or you want to use a specific
class (faster SSD, etc.), edit `01-pvc.yaml` and add a
`storageClassName:` line under `spec:`. To list available classes:

```sh
oc get storageclass
```

Look for the one marked `(default)` — that's what gets used if you
don't specify. NooBaa S3 / object storage is NOT suitable here; model
weights need block or filesystem storage.

### 3. Apply the manifests

```sh
./apply.sh
```

Or manually:

```sh
oc apply -f 00-namespace.yaml
oc apply -f 01-pvc.yaml
oc apply -f 02-deployment.yaml
oc apply -f 03-service.yaml
```

### 4. Wait for the model to download and load

First pod start downloads ~9GB from Hugging Face and loads it onto the
GPU. Expect 5-15 minutes depending on bandwidth. Watch progress:

```sh
oc logs -n vllm-vision -f deploy/vllm-vision
```

You'll see lines like:
- `Downloading shards: 100%|...`     — initial weight download
- `Loading checkpoint shards: ...`    — loading into GPU
- `INFO ... Started server process`   — ready to serve

Once you see the "Started server process" line, the endpoint is live.

### 5. Verify the endpoint

From inside the cluster (e.g. exec'ing into the scheduler pod):

```sh
curl -s http://vllm-vision.vllm-vision.svc.cluster.local:8000/v1/models | jq
# Expect: {"data":[{"id":"Qwen/Qwen2.5-VL-7B-Instruct-AWQ", ...}]}
```

If you have port-forwarding set up:

```sh
oc port-forward -n vllm-vision svc/vllm-vision 8000:8000
curl -s http://localhost:8000/v1/models
```

### 6. Configure the scheduler

In the scheduler's `01-secrets.yaml`, set:

```yaml
LLM_VISION_ENDPOINT: "http://vllm-vision.vllm-vision.svc.cluster.local:8000/v1"
LLM_VISION_MODEL:    "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"
LLM_VISION_API_KEY:  ""    # vLLM doesn't auth by default
```

Apply and roll out the scheduler.

## AMD (ROCm) hardware

vLLM has a separate ROCm container image. Edit `02-deployment.yaml`:

- Change image from `vllm/vllm-openai:v0.6.4` to `rocm/vllm:latest`
  (or pin to a specific version)
- Change resource request from `nvidia.com/gpu: 1` to `amd.com/gpu: 1`
- Add env var `HIP_VISIBLE_DEVICES: "0"` if needed
- Verify your ROCm version against vLLM's compatibility matrix

Note: vLLM's ROCm support for vision models has historically lagged
the CUDA path. If you hit issues, the workaround is to swap to a CUDA
node if available, or fall back to text-only extraction (OCR) for now.

## Troubleshooting

### Pod stuck in `Pending`
- Check node label: `oc get nodes -l gpu-tier.example.com/role=vllm-vision`
- Check GPU operator: `oc get pods -n nvidia-gpu-operator` (or `amd-gpu`)
- Check PVC bound: `oc get pvc -n vllm-vision`

### Pod `CrashLoopBackOff`
- Tail logs: `oc logs -n vllm-vision deploy/vllm-vision`
- Common causes: out-of-memory (model too big for VRAM), CUDA/ROCm
  driver mismatch, network failure during download

### "Failed to download model"
- Check egress: pod needs to reach `huggingface.co`. Test with
  `oc exec -n vllm-vision deploy/vllm-vision -- curl -sI https://huggingface.co`
- If your cluster uses an egress proxy, add HTTP_PROXY/HTTPS_PROXY env
  vars to the deployment

### Out of memory on first inference
- AWQ model loads to ~9GB; vLLM also reserves KV cache. On a 16GB GPU,
  reduce `--max-model-len` from default (8192) to 4096
- Edit the `args:` in the deployment

## Removing the deployment

```sh
oc delete -f .
# OR
oc delete namespace vllm-vision
```

This deletes the deployment, service, PVC (and the cached model). The
namespace deletion cascades.
