#!/usr/bin/env python3
# api/main.py

import os
from fastapi import FastAPI
from pydantic import BaseModel
from llama_cpp import Llama

# Path to your quantized GGUF (adjust as needed)
MODEL_PATH = os.path.expanduser(
    "~/Projects/OpenAI/TuiAi/models/quantized/mistral-7b-q4.gguf"
)

llm = Llama(
    model_path=MODEL_PATH,
    n_ctx=2048,
    n_threads=8
)

app = FastAPI()

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float = 0.7
    max_tokens: int   = 512

@app.post("/v1/chat/completions")
def chat(req: ChatRequest):
    # flatten messages into a single prompt
    prompt = "\n".join(f"{m.role}: {m.content}" for m in req.messages) + "\nassistant:"
    out = llm(
        prompt,
        max_tokens=req.max_tokens,
        temperature=req.temperature
    )
    return {
        "id":      "chatcmpl-local",
        "object":  "chat.completion",
        "model":   req.model,
        "choices": [{
            "index": 0,
            "message": {
                "role":    "assistant",
                "content": out["choices"][0]["text"],
            },
            "finish_reason": "stop"
        }]
    }

