
#!/usr/bin/env python3
import os
import json
import asyncio
import subprocess
import psutil
import aiohttp

from logging_config import get_logger
logger = get_logger("TuiAi")

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Button, Input, DataTable, Log
from textual.containers import Vertical, Horizontal
from rich.progress import Progress
from huggingface_hub import hf_hub_url, snapshot_download, list_repo_files

# 🧭 Paths
PROJECT_ROOT       = os.path.expanduser("~/Projects")
LLAMA_CPP_PATH     = os.path.join(PROJECT_ROOT, "llama.cpp")
LLAMA_CPP_QUANTIZE = os.path.join(LLAMA_CPP_PATH, "quantize")
LLAMA_CPP_MAIN     = os.path.join(LLAMA_CPP_PATH, "main")
API_SCRIPT         = os.path.expanduser("~/Projects/OpenAI/TuiAi/api/main.py")

MODEL_CACHE_FILE   = "model_cache.json"
MODEL_DIR          = "./models"
GGUF_OUTPUT_DIR    = "./models/quantized"

class ModelManager(App):
    CSS_PATH = "style.tcss"
    BINDINGS = [("q", "quit", "Quit")]

    async def log_system_info(self):
        log = self.query_one("#log-box", Log)
        while True:
            cpu  = psutil.cpu_percent()
            mem  = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/").percent
            message = f"[sys] CPU: {cpu}% | MEM: {mem}% | DISK: {disk}%"
            log.write(message)
            logger.info(message)
            await asyncio.sleep(3)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Vertical(
                Static("TuiAi - Local Model Manager and API", id="title"),
                Static("API: 🔴 OFF", id="api-status"),
                Input(placeholder="Search HF model (e.g., mistralai/Mistral-7B-v0.1)", id="search"),
                Horizontal(
                    Button(label="Download", id="download-btn"),
                    Button(label="Download Selected", id="download-selected-btn"),
                    Button(label="List GGUF", id="list-gguf-btn"),
                ),
                Horizontal(
                    Button(label="Quantize", id="quantize-btn"),
                    Button(label="Run", id="run-btn"),
                    Button(label="Toggle API", id="api-btn"),
                ),
                Static("Models / Files:", id="models-label"),
                DataTable(id="model-table")
            ),
            Vertical(
                Static("Logs:", id="logs-label"),
                Log(id="log-box", max_lines=200)
            )
        )
        yield Footer()

    def on_mount(self):
        self.model_table = self.query_one("#model-table")
        self.model_table.cursor_type = "row"
        self.log_box     = self.query_one("#log-box")
        self.api_proc    = None
        self.load_cache()
        asyncio.create_task(self.log_system_info())

    def write_log(self, message: str):
        self.log_box.write(message)
        logger.info(message)

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
        query  = self.query_one("#search", Input).value.strip()
        btn_id = event.button.id

        if not query and btn_id not in {"api-btn","download-selected-btn","list-gguf-btn"}:
            return

        if btn_id == "download-btn":
            self.model_table.add_row(query, "Downloading…")
            await self.download_model(query)

        elif btn_id == "download-selected-btn":
            row = self.model_table.cursor_row
            if row is None:
                return
            selected = self.model_table.get_row_at(row)[0]
            if not selected.endswith(".gguf"):
                self.log_box.write("⚠️ Not a GGUF file")
                logger.warning("Download Selected pressed on non-gguf file")
                return
            await self.download_gguf_with_progress(query, selected)

        elif btn_id == "list-gguf-btn":
            await self.list_gguf_files(query)

        elif btn_id == "quantize-btn":
            await self.quantize_model(query)

        elif btn_id == "run-btn":
            await self.run_model(query)

        elif btn_id == "api-btn":
            await self.toggle_api()

    async def list_gguf_files(self, model_id):
        try:
            files = list_repo_files(model_id)
            ggufs = [f for f in files if f.endswith(".gguf")]
            self.model_table.clear()
            self.model_table.add_row("Available .gguf files:", "")
            for fname in ggufs:
                self.model_table.add_row(fname, "Available")
            if not ggufs:
                self.model_table.add_row("No GGUF files found", "")
        except Exception:
            logger.exception("Failed to list GGUF files")
            self.model_table.add_row("Error", "See logs for details")

    async def download_model(self, model_id):
        base_dir = os.path.join(MODEL_DIR, model_id.replace("/", "__"))
        os.makedirs(base_dir, exist_ok=True)
        try:
            snapshot_download(
                repo_id=model_id,
                local_dir=base_dir,
                local_dir_use_symlinks=False,
                allow_patterns=["*.gguf"]
            )
            self.update_cache(model_id, "Downloaded")
            self.write_log(f"✅ Model files downloaded to: {base_dir}")
        except Exception:
            logger.exception(f"Download error for model {model_id}")
            self.update_cache(model_id, "Download failed")

    async def download_gguf_with_progress(self, model_id, gguf_filename):
        file_url  = hf_hub_url(model_id, filename=gguf_filename)
        base_name = model_id.replace("/", "__")
        local_dir = os.path.join(MODEL_DIR, base_name)
        os.makedirs(local_dir, exist_ok=True)
        local_path= os.path.join(local_dir, gguf_filename)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(file_url) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("Content-Length", 0))
                    downloaded = 0
                    with open(local_path, "wb") as f, Progress() as progress:
                        task = progress.add_task(f"📦 Downloading {gguf_filename}", total=total)
                        async for chunk in resp.content.iter_chunked(1024):
                            f.write(chunk)
                            downloaded += len(chunk)
                            progress.update(task, completed=downloaded)
            self.update_cache(model_id, f"Downloaded: {gguf_filename}")
            self.write_log(f"✅ Saved to: {local_path}")
        except Exception:
            logger.exception(f"Failed to download {gguf_filename}")

    async def quantize_model(self, model_id):
        base_name = model_id.replace("/", "__")
        f16_path  = os.path.join(MODEL_DIR, base_name, "mistral-f16.gguf")
        q4_path   = os.path.join(GGUF_OUTPUT_DIR, f"{base_name}-q4.gguf")
        os.makedirs(GGUF_OUTPUT_DIR, exist_ok=True)

        if not os.path.exists(f16_path):
            self.write_log(f"⚠️ .gguf file not found for {model_id}")
            return

        try:
            subprocess.run([LLAMA_CPP_QUANTIZE, f16_path, q4_path, "Q4_0"], check=True)
            self.update_cache(model_id, "Quantized (Q4_0)")
            self.write_log(f"✅ Quantized model saved to: {q4_path}")
        except Exception:
            logger.exception(f"Quantization error for {model_id}")

    async def run_model(self, model_id):
        base_name = model_id.replace("/", "__")
        q4_path   = os.path.join(GGUF_OUTPUT_DIR, f"{base_name}-q4.gguf")
        if not os.path.exists(q4_path):
            self.write_log("⚠️ Quantized model not found")
            return
        try:
            subprocess.Popen([LLAMA_CPP_MAIN, "-m", q4_path, "-i"])

