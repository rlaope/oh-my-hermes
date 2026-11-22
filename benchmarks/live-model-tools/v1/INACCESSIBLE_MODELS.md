# Inaccessible Models Registry

This registry tracks models that need contributor measurements due to paid API access requirements or unavailable hardware. Each entry includes vendor documentation links and references to contributor measurement attempts.

## A. Calibrated family, never measured (paid API)

| Model | Vendor | Issue | Vendor Documentation | Measurement Status | Last Updated |
|-------|--------|-------|---------------------|-------------------|--------------|
| gemini-4-argon | Google | #3078 | [Link] | Not attempted | - |
| grok-build-0.1 | xAI | #3079 | [Link] | Not attempted | - |
| kimi-k3.1-pro | Moonshot AI | #3080 | [Link] | Not attempted | - |
| glm-5.3 | Z.ai | #3081 | [Link] | Not attempted | - |
| qwen4-max | Alibaba | #3082 | [Link] | Not attempted | - |
| qwen3-coder | Alibaba | #3083 | [Link] | Not attempted | - |
| deepseek-v4-pro-0813 | DeepSeek | #3084 | [Link] | Not attempted | - |
| mistral-large-4-0 | Mistral | #3085 | [Link] | Not attempted | - |
| llama-4-maverick | Meta | #3086 | [Link] | Not attempted | - |
| solar-pro4 | Upstage | #3087 | [Link] | Not attempted | - |

## B. Generic fallback: does it need its own block? (paid API)

| Model | Vendor | Issue | Vendor Documentation | Measurement Status | Last Updated |
|-------|--------|-------|---------------------|-------------------|--------------|
| devstral-2512 | Mistral | #3088 | [Link] | Not attempted | - |
| minimax-m3 | MiniMax | #3089 | [Link] | Not attempted | - |
| command-a-plus | Cohere | #3090 | [Link] | Not attempted | - |
| nova-premier-v1 | Amazon | #3091 | [Link] | Not attempted | - |
| mimo-v2.6-pro | Xiaomi | #3092 | [Link] | Not attempted | - |
| step-5-preview | StepFun | #3093 | [Link] | Not attempted | - |
| hy4 | Tencent | #3094 | [Link] | Not attempted | - |
| seed-2-1-turbo | ByteDance Seed | #3095 | [Link] | Not attempted | - |
| nemotron-3.5-super-vl | NVIDIA | #3096 | [Link] | Not attempted | - |
| muse-spark-1.3 | Meta | #3097 | [Link] | Not attempted | - |
| inkling | Thinking Machines | #3098 | [Link] | Not attempted | - |
| fugu-max | Sakana AI | #3099 | [Link] | Not attempted | - |
| gemini-4-carbon | Google | #3100 | [Link] | Not attempted | - |

## C. Self-hosted open weights / other hardware (contributor GPU)

| Model | Vendor | Issue | Vendor Documentation | Measurement Status | Last Updated |
|-------|--------|-------|---------------------|-------------------|--------------|
| Qwen3-Coder-480B-A35B-Instruct | Alibaba | #3101 | [Link] | Not attempted | - |
| GLM-5.3 | Z.ai | #3102 | [Link] | Not attempted | - |
| DeepSeek-V4.1-Flash | DeepSeek | #3103 | [Link] | Not attempted | - |
| Kimi-K3.1-Pro | Moonshot AI | #3104 | [Link] | Not attempted | - |
| Llama-4-Scout-17B-16E-Instruct | Meta | #3105 | [Link] | Not attempted | - |
| Devstral-2-123B-Instruct-2512 | Mistral | #3106 | [Link] | Not attempted | - |
| MiniMax-M3.1-Flash | MiniMax | #3107 | [Link] | Not attempted | - |
| OMH tool loop | - | #3108 | [Link] | Not attempted | - |
| OMH tool loop | - | #3109 | [Link] | Not attempted | - |
| OMH tool loop | - | #3110 | [Link] | Not attempted | - |

## Measurement Status Legend

- **Not attempted**: No measurement attempt has been made yet
- **In Progress**: A contributor is currently working on measurement
- **Blocked**: Measurement is currently impossible (e.g., cost, hardware)
- **Completed**: Full baseline and optimized measurements are available

## How to Contribute

1. Choose a model from the list above
2. Create a new measurement attempt using the [CONTRIBUTOR_MEASUREMENT_TRACKER.md](CONTRIBUTOR_MEASUREMENT_TRACKER.md) template
3. Update this registry with your attempt status
4. Submit a pull request with your findings

## Contributing Guidelines

- Be honest about access limitations and challenges
- Provide as much vendor documentation as possible
- Include cost estimates if applicable
- Update status fields as work progresses
- Link to your measurement attempt in the registry
