# model_manager/app.py
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Button, Input, DataTable
from textual.containers import Vertical, Horizontal
from huggingface_hub import snapshot_download
import json
import os
import subprocess

# Use absolute paths for llama.cpp binaries relative to project root
PROJECT_ROOT = os.path.expanduser("~/Projects")
LLAMA_CPP_PATH = os.path.join(PROJECT_ROOT, "llama.cpp")
LLAMA_CPP_QUANTIZE = os.path.join(LLAMA_CPP_PATH, "quantize")
LLAMA_CPP_MAIN = os.path.join(LLAMA_CPP_PATH, "main")

MODEL_CACHE_FILE = "model_cache.json"
MODEL_DIR = "./models"
GGUF_OUTPUT_DIR = "./models/quantized"

class ModelManager(App):
    CSS_PATH = "style.tcss"
    BINDINGS = [("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("Your Local Model Manager", id="title"),
            Input(placeholder="Search HF model (e.g., mistralai/Mistral-7B-v0.1)", id="search"),
            Horizontal(
                Button(label="Download", id="download-btn"),
                Button(label="Quantize", id="quantize-btn"),
                Button(label="Run", id="run-btn"),
            ),
            Static("Models:", id="models-label"),
            DataTable(id="model-table"),
        )
        yield Footer()

    def on_mount(self):
        self.model_table = self.query_one("#model-table", DataTable)
        self.model_table.add_columns("Name", "Status")
        self.load_cache()

    def load_cache(self):
        if os.path.exists(MODEL_CACHE_FILE):
            with open(MODEL_CACHE_FILE, "r") as f:
                models = json.load(f)
                for name, entry in models.items():
                    self.model_table.add_row(name, entry["status"])

    def update_cache(self, name, status):
        models = {}
        if os.path.exists(MODEL_CACHE_FILE):
            with open(MODEL_CACHE_FILE, "r") as f:
                models = json.load(f)
        models[name] = {"status": status}
        with open(MODEL_CACHE_FILE, "w") as f:
            json.dump(models, f, indent=2)

    async def on_button_pressed(self, event: Button.Pressed):
        query = self.query_one("#search", Input).value.strip()
        if not query:
            return

        if event.button.id == "download-btn":
            self.model_table.add_row(query, "Downloading...")
            await self.download_model(query)

        elif event.button.id == "quantize-btn":
            await self.quantize_model(query)

        elif event.button.id == "run-btn":
            await self.run_model(query)

    async def download_model(self, model_id):
        local_path = os.path.join(MODEL_DIR, model_id.replace("/", "__"))
        os.makedirs(local_path, exist_ok=True)
        try:
            snapshot_download(repo_id=model_id, local_dir=local_path, local_dir_use_symlinks=False)
            self.update_cache(model_id, "Downloaded")
        except Exception as e:
            self.update_cache(model_id, f"Error: {str(e)}")

    async def quantize_model(self, model_id):
        base_name = model_id.replace("/", "__")
        f16_path = os.path.join(MODEL_DIR, base_name, "mistral-f16.gguf")
        q4_path = os.path.join(GGUF_OUTPUT_DIR, f"{base_name}-q4.gguf")
        os.makedirs(GGUF_OUTPUT_DIR, exist_ok=True)

        if not os.path.exists(f16_path):
            self.update_cache(model_id, "Missing .gguf file, please convert first")
            return

        try:
            subprocess.run([LLAMA_CPP_QUANTIZE, f16_path, q4_path, "Q4_0"], check=True)
            self.update_cache(model_id, "Quantized (Q4_0)")
        except subprocess.CalledProcessError as e:
            self.update_cache(model_id, f"Quantize failed: {str(e)}")

    async def run_model(self, model_id):
        base_name = model_id.replace("/", "__")
        q4_path = os.path.join(GGUF_OUTPUT_DIR, f"{base_name}-q4.gguf")
        if not os.path.exists(q4_path):
            self.update_cache(model_id, "Quantized model not found")
            return

        try:
            subprocess.Popen([LLAMA_CPP_MAIN, "-m", q4_path, "-i"])
            self.update_cache(model_id, "Running in terminal...")
        except Exception as e:
            self.update_cache(model_id, f"Run failed: {str(e)}")

if __name__ == "__main__":
    os.makedirs(MODEL_DIR, exist_ok=True)
    ModelManager().run()