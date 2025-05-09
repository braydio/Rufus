Rufus

# Model Manager Development Plan

## Completed Features

* [x] Textual TUI with header, footer, and layout
* [x] Input for Hugging Face model ID
* [x] Download HF models via `huggingface_hub`
* [x] Local cache of downloaded models (JSON)
* [x] Display model status in a table
* [x] Quantization with llama.cpp `quantize`
* [x] Run quantized model via llama.cpp `main`
* [x] Absolute path support for llama.cpp tools

## Planned Features

* [ ] Auto-convert `.safetensors` to `.gguf` if missing
* [ ] Model metadata viewer (filesize, tokens, etc.)
* [ ] TUI status popup or modal for tasks
* [ ] Chat interface to test models inline
* [ ] Delete model from disk/cache
* [ ] Download models from a preset list
* [ ] Color status indicators (e.g. downloaded, quantized, error)
* [ ] GGUF conversion logging panel
* [ ] Backend API server option (FastAPI)

---

## Summary

This project is a lightweight terminal-based interface for managing large language models locally using `llama.cpp`. It is built with Python and the `textual` framework, and supports downloading models from Hugging Face, tracking them in a local cache, quantizing them for CPU inference, and running them directly. Planned features will extend functionality with conversion tools, interactive chat, metadata inspection, and a possible backend API for remote use.
