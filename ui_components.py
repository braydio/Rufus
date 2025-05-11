# ui_components.py
from textual.containers import Vertical, Horizontal
from textual.widgets import Static, Input, Button, DataTable, Log

class ControlPanel(Vertical):
    """Top‐left: title, API status, search + action buttons."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mount(Static("TuiAi - Local Model Manager and API", id="title"))
        self.mount(Static("API: 🔴 OFF", id="api-status"))
        self.mount(Input(placeholder="Search HF model…", id="search"))
        # download / list 
        self.mount(
            Horizontal(
                Button("Download", id="download-btn"),
                Button("Download Selected", id="download-selected-btn"),
                Button("List GGUF", id="list-gguf-btn"),
            )
        )
        # quantize / run / api toggle
        self.mount(
            Horizontal(
                Button("Quantize", id="quantize-btn"),
                Button("Run", id="run-btn"),
                Button("Toggle API", id="api-btn"),
            )
        )
        self.mount(Static("Models / Files:", id="models-label"))

class ModelListPanel(Vertical):
    """Bottom‐left: table of models/files."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.table = DataTable(id="model-table")
        self.table.add_columns("Name", "Status")
        self.mount(self.table)

class LogPanel(Vertical):
    """Right‐side logs panel."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mount(Static("Logs:", id="logs-label"))
        self.log = Log(id="log-box", max_lines=200)
        self.mount(self.log)
