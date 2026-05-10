#!/usr/bin/env python3
import os
import sys
import subprocess
import json
import hashlib
from pathlib import Path
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, DirectoryTree, SelectionList, 
    Input, Label, Button, RichLog, Static, TabbedContent, TabPane
)
from textual.binding import Binding
from textual import on, work
from rich.syntax import Syntax
from rich.text import Text

CACHE_DIR = Path(".build_cache")
MANIFEST_FILE = CACHE_DIR / "manifest.json"

class LLVMLabApp(App):
    CSS = """
    Screen {
        layout: horizontal;
    }
    #sidebar {
        width: 40;
        border-right: tall $primary;
        background: $surface;
    }
    #main-content {
        width: 1fr;
    }
    .section-label {
        background: $primary;
        color: $text;
        padding: 0 1;
        margin: 1 0 0 0;
        text-style: bold;
    }
    #log-view, #ir-view {
        height: 1fr;
        border: solid $primary;
        background: $surface;
    }
    #controls {
        height: auto;
        border-bottom: tall $primary;
        padding: 1;
    }
    Input {
        margin-bottom: 1;
    }
    Button {
        width: 100%;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "run_opt", "Run Optimization"),
    ]

    def __init__(self):
        super().__init__()
        self.selected_source = None
        self.selected_plugins = []
        self.manifest = self.load_manifest()
        self.project_root = Path(__file__).parent.resolve()

    def update_compile_commands(self, file_path, command):
        compdb_path = self.project_root / "compile_commands.json"
        db = []
        if compdb_path.exists():
            try:
                with open(compdb_path, "r") as f:
                    db = json.load(f)
            except json.JSONDecodeError:
                db = []
        
        abs_file = str(Path(file_path).resolve())
        # Remove existing entry for this file
        db = [entry for entry in db if entry["file"] != abs_file]
        
        db.append({
            "directory": str(self.project_root),
            "command": " ".join(command),
            "file": abs_file
        })
        
        with open(compdb_path, "w") as f:
            json.dump(db, f, indent=2)

    def load_manifest(self):
        if MANIFEST_FILE.exists():
            with open(MANIFEST_FILE, "r") as f:
                return json.load(f)
        return {"files": {}}

    def save_manifest(self):
        with open(MANIFEST_FILE, "w") as f:
            json.dump(self.manifest, f, indent=2)

    def get_file_hash(self, path):
        hasher = hashlib.md5()
        with open(path, "rb") as f:
            buf = f.read()
            hasher.update(buf)
        return hasher.hexdigest()

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="sidebar"):
            yield Label("SOURCES (code/)", classes="section-label")
            yield DirectoryTree("code/", id="source-tree")
            yield Label("PLUGINS (plugins/)", classes="section-label")
            plugin_options = [
                (p.name, str(p), False) 
                for p in Path("plugins").glob("*.cpp")
            ]
            yield SelectionList(*plugin_options, id="plugin-list")
            
        with Vertical(id="main-content"):
            with Vertical(id="controls"):
                yield Label("Clang Flags:")
                yield Input(value="-O1", placeholder="-O1 -g ...", id="clang-flags")
                yield Label("Opt Pipeline:")
                yield Input(value="default<O2>", placeholder="default<O2>, mem2reg, ...", id="opt-pipeline")
                yield Button("RUN OPTIMIZATION", variant="primary", id="run-btn")

            with TabbedContent():
                with TabPane("Logs", id="logs-tab"):
                    yield RichLog(id="log-view", highlight=True, markup=True)
                with TabPane("IR Output", id="ir-tab"):
                    yield ScrollableContainer(Static(id="ir-view"))
        yield Footer()

    @on(DirectoryTree.FileSelected)
    def handle_file_selection(self, event: DirectoryTree.FileSelected) -> None:
        if event.path.suffix in (".cpp", ".c"):
            self.selected_source = event.path
            self.log_message(f"[green]Selected source:[/green] {event.path.name}")

    @on(SelectionList.SelectedChanged)
    def handle_plugin_selection(self, event: SelectionList.SelectedChanged) -> None:
        self.selected_plugins = [Path(p) for p in event.selection_list.selected]
        self.log_message(f"[green]Selected plugins:[/green] {', '.join(p.name for p in self.selected_plugins)}")

    @on(Button.Pressed, "#run-btn")
    def action_run_opt(self) -> None:
        self.run_process()

    def log_message(self, message: str):
        log_view = self.query_one("#log-view", RichLog)
        log_view.write(message)

    @work(exclusive=True)
    async def run_process(self):
        if not self.selected_source:
            self.log_message("[red]Error: No source file selected![/red]")
            return

        log_view = self.query_one("#log-view", RichLog)
        log_view.clear()
        self.log_message(f"--- Starting Optimization Workflow at {datetime.now().strftime('%H:%M:%S')} ---")

        clang_flags = self.query_one("#clang-flags", Input).value
        opt_pipeline = self.query_one("#opt-pipeline", Input).value
        
        # 1. Compile Source to IR
        ir_file = await self.compile_source(self.selected_source, clang_flags)
        if not ir_file: return

        # 2. Compile Plugins
        plugin_libs = []
        for p_src in self.selected_plugins:
            lib = await self.compile_plugin(p_src)
            if not lib: return
            plugin_libs.append(lib)

        # 3. Run Opt
        await self.run_opt(ir_file, plugin_libs, opt_pipeline)
        
        self.save_manifest()
        self.log_message("[bold green]Workflow completed successfully![/bold green]")

    async def compile_source(self, src_path, flags):
        h = self.get_file_hash(src_path)
        cache_key = f"src_{src_path.name}_{hash(flags)}"
        out_path = CACHE_DIR / f"{src_path.stem}.ll"
        
        # Use opt-20 or fallback
        clang = self.find_tool("clang++")
        cmd = [clang, "-S", "-emit-llvm"] + flags.split() + [str(src_path), "-o", str(out_path)]
        self.update_compile_commands(src_path, cmd)

        if self.manifest["files"].get(cache_key) == h and out_path.exists():
            self.log_message(f"Using cached IR for {src_path.name}")
            return out_path

        self.log_message(f"Compiling {src_path.name} to IR...")
        if await self.exec_cmd(cmd):
            self.manifest["files"][cache_key] = h
            return out_path
        return None

    async def compile_plugin(self, p_src):
        h = self.get_file_hash(p_src)
        cache_key = f"plugin_{p_src.name}"
        out_path = CACHE_DIR / f"{p_src.stem}.so"

        llvm_config = self.find_tool("llvm-config")
        cxxflags = subprocess.check_output([llvm_config, "--cxxflags"], text=True).strip().split()
        ldflags = subprocess.check_output([llvm_config, "--ldflags"], text=True).strip().split()
        
        clang_cpp = self.find_tool("clang++")
        cmd = [clang_cpp, "-shared", "-fPIC"] + cxxflags + [str(p_src)] + ldflags + ["-o", str(out_path)]
        self.update_compile_commands(p_src, cmd)

        if self.manifest["files"].get(cache_key) == h and out_path.exists():
            self.log_message(f"Using cached plugin {p_src.name}")
            return out_path

        self.log_message(f"Building plugin {p_src.name}...")
        if await self.exec_cmd(cmd):
            self.manifest["files"][cache_key] = h
            return out_path
        return None

    async def run_opt(self, ir_file, plugins, pipeline):
        self.log_message(f"Running optimizer with pipeline: {pipeline}...")
        opt = self.find_tool("opt")
        out_path = CACHE_DIR / f"{ir_file.stem}.opt.ll"
        
        cmd = [opt]
        for p in plugins:
            cmd.append(f"-load-pass-plugin={p}")
        cmd.append(f"-passes={pipeline}")
        cmd.extend([str(ir_file), "-S", "-o", str(out_path)])
        
        if await self.exec_cmd(cmd):
            content = out_path.read_text()
            ir_view = self.query_one("#ir-view", Static)
            ir_view.update(Syntax(content, "llvm", theme="monokai", line_numbers=True))
            self.query_one(TabbedContent).active = "ir-tab"
            return out_path
        return None

    async def exec_cmd(self, cmd):
        self.log_message(f"[dim]Exec: {' '.join(cmd)}[/dim]")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if stdout:
            self.log_message(stdout.decode())
        if stderr:
            self.log_message(f"[yellow]{stderr.decode()}[/yellow]")
            
        if proc.returncode != 0:
            self.log_message(f"[red]Command failed with exit code {proc.returncode}[/red]")
            return False
        return True

    def find_tool(self, tool_name):
        for v in ["-20", "-18", "-17", ""]:
            name = f"{tool_name}{v}"
            try:
                subprocess.run([name, "--version"], capture_output=True)
                return name
            except FileNotFoundError:
                continue
        return tool_name

import asyncio
if __name__ == "__main__":
    app = LLVMLabApp()
    app.run()
