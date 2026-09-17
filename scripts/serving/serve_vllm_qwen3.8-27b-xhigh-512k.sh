#!/bin/bash
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --job-name=serve-qwen3.8-27b-512k
#SBATCH --cpus-per-task=96
#SBATCH --gpus-per-task=8
#SBATCH --mem=0
#SBATCH --gres=gpu:8
#SBATCH --partition=main
#SBATCH --output=slurm_%x_%j.out

set -euo pipefail

SQSH=/mnt/weka/shrd/k2m/suqi.sun/bbq_image/vllm0240-ifm-parsers-fef2b07-cu128.sqsh
MODEL=/mnt/weka/home/yuan.huang/latest_model_test/models/Qwen3.8-27B
SERVED_MODEL_NAME=Qwen3.8-27B-512K
REASONING_PARSER=qwen3
TOOL_CALL_PARSER=qwen3_xml
TP_SIZE=8
MAX_MODEL_LEN=524288
PORT=8080

# Qwen3.8-27B is native at 262,144 tokens. This official-style static YaRN
# configuration uses factor 2.0 for a 524,288-token service. Static YaRN also
# affects shorter requests, so keep the native 262K service for A/B comparison.
YARN_OVERRIDES='{"text_config":{"rope_parameters":{"mrope_interleaved":true,"mrope_section":[11,11,10],"rope_type":"yarn","rope_theta":10000000,"partial_rotary_factor":0.25,"factor":2.0,"original_max_position_embeddings":262144}}}'
export VLLM_ALLOW_LONG_MAX_MODEL_LEN=1

if [[ ! -f "${SQSH}" ]]; then
  echo "Container image not found: ${SQSH}" >&2
  exit 1
fi

if [[ ! -d "${MODEL}" ]]; then
  echo "Model directory not found: ${MODEL}" >&2
  exit 1
fi

echo "Endpoint: http://$(hostname):${PORT}/v1"
echo "Model: ${MODEL}"
echo "Served model name: ${SERVED_MODEL_NAME}"
echo "Maximum context: ${MAX_MODEL_LEN} (static YaRN factor 2.0)"
echo "Default reasoning effort: xhigh"

srun \
  --container-image="${SQSH}" \
  --container-writable \
  --container-mounts="${MODEL}:/model" \
  vllm serve /model \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --served-model-name "${SERVED_MODEL_NAME}" \
    --tensor-parallel-size "${TP_SIZE}" \
    --max-model-len "${MAX_MODEL_LEN}" \
    --hf-overrides "${YARN_OVERRIDES}" \
    --kv-cache-dtype fp8 \
    --reasoning-parser "${REASONING_PARSER}" \
    --enable-auto-tool-choice \
    --tool-call-parser "${TOOL_CALL_PARSER}" \
    --default-chat-template-kwargs '{"enable_thinking":true,"reasoning_effort":"xhigh","preserve_thinking":true}' \
    --enable-prefix-caching
