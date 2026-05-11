#!/usr/bin/env python3
import os
import sys
import subprocess
import json
import hashlib
import asyncio
import re
import shutil
from pathlib import Path
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header,
    Footer,
    DirectoryTree,
    SelectionList,
    Input,
    Label,
    Button,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
    Tree,
    Checkbox,
    Select,
)
from textual.binding import Binding
from textual import on, work
from rich.syntax import Syntax
from rich.text import Text

CACHE_DIR = Path(".build_cache")
MANIFEST_FILE = CACHE_DIR / "manifest.json"


class PipelineNode:
    def __init__(self, name, params=None, children=None, enabled=True):
        self.name = name
        self.params = params or ""
        self.children = children or []
        self.enabled = enabled

    def to_string(self):
        if not self.enabled:
            return ""

        if self.children:
            inner = ",".join(filter(None, [c.to_string() for c in self.children]))
            if not inner:
                return ""
            return f"{self.name}{self.params}({inner})"

        return self.name + self.params


def parse_pipeline(s):
    import re

    # Match pass names, parameters in <>, and structural characters ( ) ,
    tokens = re.findall(r"[a-zA-Z0-9_-]+|<[^>]+>|\(|\)|,", s)
    pos = 0

    def parse_element():
        nonlocal pos
        name = tokens[pos]
        pos += 1
        params = ""
        if pos < len(tokens) and tokens[pos].startswith("<"):
            params = tokens[pos]
            pos += 1

        children = []
        if pos < len(tokens) and tokens[pos] == "(":
            pos += 1
            while pos < len(tokens) and tokens[pos] != ")":
                children.append(parse_element())
                if pos < len(tokens) and tokens[pos] == ",":
                    pos += 1
            if pos < len(tokens) and tokens[pos] == ")":
                pos += 1
        return PipelineNode(name, params, children)

    def parse_list():
        nonlocal pos
        elements = []
        while pos < len(tokens):
            elements.append(parse_element())
            if pos < len(tokens) and tokens[pos] == ",":
                pos += 1
            elif pos < len(tokens) and tokens[pos] == ")":
                break
        return elements

    if not tokens:
        return PipelineNode("module")

    elements = parse_list()
    # If the root is already a module(...) or similar, return it
    if len(elements) == 1 and elements[0].children:
        return elements[0]
    # Otherwise wrap in a module manager
    return PipelineNode("module", "", elements)


class PipelineEditor(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("PIPELINE EDITOR", classes="section-label")
        with Horizontal(id="pipeline-header"):
            yield Button("O0", id="preset-O0", classes="preset-btn")
            yield Button("O1", id="preset-O1", classes="preset-btn")
            yield Button("O2", id="preset-O2", classes="preset-btn")
            yield Button("O3", id="preset-O3", classes="preset-btn")
            yield Button("Os", id="preset-Os", classes="preset-btn")
        tree = Tree("Pipeline", id="pipeline-tree")
        tree.root.allow_expand = False
        yield tree
        with Horizontal(id="pipeline-add-row"):
            yield Input(placeholder="pass-name", id="new-pass-name")
            yield Button("ADD", id="add-pass-btn")
            yield Button("MOD", id="modify-pass-btn")
            yield Button("DEL", id="remove-pass-btn")
            yield Button("↑", id="move-up-btn", classes="nav-btn")
            yield Button("↓", id="move-down-btn", classes="nav-btn")

    def load_pipeline(self, s):
        tree = self.query_one("#pipeline-tree", Tree)
        tree.clear()
        root_node = parse_pipeline(s)
        self.build_tree(tree.root, root_node)
        tree.root.expand_all()

    def build_tree(self, tree_node, pipe_node):
        tree_node.data = pipe_node
        # Use dim styling for disabled nodes, normal for enabled
        label = f"{pipe_node.name}{pipe_node.params}"
        if not pipe_node.enabled:
            tree_node.label = Text(label, style="dim")
        else:
            tree_node.label = Text(label)

        tree_node.allow_expand = False
        for child in pipe_node.children:
            new_tree_node = tree_node.add(child.name, data=child)
            self.build_tree(new_tree_node, child)

    def get_pipeline_string(self):
        tree = self.query_one("#pipeline-tree", Tree)
        if tree.root.data:
            return tree.root.data.to_string()
        return ""


class LLVMLabApp(App):
    CSS = """
    Screen {
        layout: horizontal;
    }
    #config-tab {
        layout: horizontal;
    }
    #sidebar {
        width: 15%;
        border-right: tall $primary;
        background: $surface;
    }
    #pipeline-col {
        width: 50%;
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
    #log-view, #ir-view, #status-log {
        height: 1fr;
        border: solid $primary;
        background: $surface;
    }
    #controls {
        height: 1fr;
        padding: 1;
    }
    #pipeline-header {
        height: auto;
        margin-bottom: 1;
    }
    .preset-btn {
        width: auto;
        min-width: 6;
        margin-right: 1;
        margin-top: 0;
        height: 3;
    }
    #pipeline-tree {
        height: 1fr;
        border: solid $primary;
    }
    #pipeline-add-row {
        height: auto;
        padding: 0 1;
        margin-top: 1;
    }
    #pipeline-add-row Input {
        width: 3fr;
        margin: 0;
    }
    #pipeline-add-row Button {
        width: auto;
        min-width: 6;
        margin: 0 0 0 1;
        height: 3;
    }
    .nav-btn {
        width: 4;
        margin-left: 1;
        height: 3;
    }
    #pipeline-actions {
        display: none;
    }
    #main-tabs {
        height: 1fr;
    }
    #ir-container {
        height: 1fr;
        border: solid $primary;
    }
    #run-row {
        height: auto;
        margin-top: 1;
    }
    #llvm-version-select {
        width: 1fr;
        margin-right: 1;
    }
    #run-btn {
        width: 2fr;
        margin-top: 0;
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
        Binding("space", "toggle_pass", "Toggle Pass"),
        Binding("ctrl+up", "move_up", "Move Pass Up"),
        Binding("ctrl+down", "move_down", "Move Pass Down"),
    ]

    def action_toggle_pass(self) -> None:
        tree = self.query_one("#pipeline-tree", Tree)
        node = tree.cursor_node
        if node and hasattr(node, "data") and isinstance(node.data, PipelineNode):
            node.data.enabled = not node.data.enabled
            label = f"{node.data.name}{node.data.params}"
            if not node.data.enabled:
                node.label = Text(label, style="dim")
            else:
                node.label = Text(label)

    def __init__(self):
        super().__init__()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.selected_source = None
        self.selected_plugins = []
        self.manifest = self.load_manifest()
        self.project_root = Path(__file__).parent.resolve()
        self._is_refreshing = False
        self._first_load = True
        self.available_versions = self.discover_llvm_versions()

    def discover_llvm_versions(self):
        versions = set()
        # Look for clang++-XX in PATH
        path_dirs = os.environ.get("PATH", "").split(os.pathsep)
        for d in path_dirs:
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                if f.startswith("clang++"):
                    suffix = f[len("clang++"):]
                    if not suffix or (suffix.startswith("-") and suffix[1:].isdigit()):
                        versions.add(suffix)
        
        # Sort versions: numeric suffixes first (descending), then empty suffix
        sorted_versions = sorted(
            list(versions),
            key=lambda x: (int(x[1:]) if x.startswith("-") and x[1:].isdigit() else -1),
            reverse=True
        )
        
        choices = []
        for v in sorted_versions:
            label = f"LLVM {v[1:]}" if v.startswith("-") else "Default"
            choices.append((label, v))
        
        if not choices:
            choices = [("Default", "")]
        return choices

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

        db.append(
            {
                "directory": str(self.project_root),
                "command": " ".join(command),
                "file": abs_file,
            }
        )

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

        with TabbedContent(id="main-tabs"):
            with TabPane("CONFIG", id="config-tab"):
                with Horizontal():
                    # Sidebar
                    with Vertical(id="sidebar"):
                        yield Label("SELECTED SOURCE:", classes="section-label")
                        yield Label("None", id="selected-source-label")
                        yield Label("SOURCES (code/)", classes="section-label")
                        yield DirectoryTree("code/", id="source-tree")
                        yield Label("PLUGINS (plugins/)", classes="section-label")
                        yield SelectionList(id="plugin-list")

                    # Pipeline Editor
                    with Vertical(id="pipeline-col"):
                        yield PipelineEditor(id="pipeline-editor")

                    # Config & Status
                    with Vertical(id="main-content"):
                        with Vertical(id="controls"):
                            yield Label("CLANG FLAGS", classes="section-label")
                            yield Input(
                                value="-O0",
                                placeholder="-O1 -g ...",
                                id="clang-flags",
                            )
                            yield Checkbox(
                                "Strip optnone/noinline attributes",
                                id="strip-optnone",
                                value=True,
                            )
                            yield Label("STATUS", classes="section-label")
                            yield RichLog(id="status-log", highlight=True, markup=True)
                            with Horizontal(id="run-row"):
                                yield Select(
                                    self.available_versions,
                                    value=self.available_versions[0][1],
                                    id="llvm-version-select",
                                    allow_blank=False
                                )
                                yield Button(
                                    "RUN OPTIMIZATION", variant="primary", id="run-btn"
                                )

            with TabPane("IR VIEWER", id="ir-tab"):
                yield ScrollableContainer(Static(id="ir-view"), id="ir-container")

            with TabPane("DETAILED LOGS", id="logs-tab"):
                yield RichLog(id="log-view", highlight=True, markup=True, wrap=True)

        yield Footer()

    @on(DirectoryTree.FileSelected)
    def handle_file_selection(self, event: DirectoryTree.FileSelected) -> None:
        if event.path.suffix in (".cpp", ".c", ".ll"):
            self.selected_source = event.path
            self.query_one("#selected-source-label", Label).update(
                f"[bold cyan]{event.path.name}[/bold cyan]"
            )
            self.log_message(f"[green]Selected source:[/green] {event.path.name}")

    @on(SelectionList.SelectedChanged)
    def handle_plugin_selection(self, event: SelectionList.SelectedChanged) -> None:
        self.selected_plugins = [Path(p) for p in event.selection_list.selected]
        if not self._is_refreshing:
            self.log_message(
                f"[green]Selected plugins:[/green] {', '.join(p.name for p in self.selected_plugins)}"
            )

    @on(Button.Pressed, "#run-btn")
    def action_run_opt(self) -> None:
        self.run_process()

    def on_mount(self) -> None:
        self.refresh_files()
        self.set_interval(2.0, self.refresh_files)

        # Load pipeline from cache if it exists, else default O1
        pipeline_file = CACHE_DIR / "pipeline.ll"
        if pipeline_file.exists():
            try:
                with open(pipeline_file, "r") as f:
                    pipeline_str = f.read()
                self.query_one("#pipeline-editor", PipelineEditor).load_pipeline(
                    pipeline_str
                )
                self.log_message("[green]Pipeline loaded from cache.[/green]")
            except:
                self.run_worker(self.load_preset("O1"))
        else:
            self.run_worker(self.load_preset("O1"))

        # Auto-select first available source
        sources = sorted(Path("code").glob("*.cpp"))
        if sources:
            self.selected_source = sources[0]
            self.query_one("#selected-source-label", Label).update(
                f"[bold cyan]{self.selected_source.name}[/bold cyan]"
            )
            self.log_message(
                f"[green]Auto-selected source:[/green] {self.selected_source.name}"
            )

    async def load_preset(self, level):
        opt = self.find_tool("opt")
        # -print-pipeline-passes output is sent to stdout
        cmd = [
            opt,
            f"-{level}",
            "-print-pipeline-passes",
            "/dev/null",
            "-S",
            "-o",
            "/dev/null",
        ]
        self.log_message(f"Fetching {level} pipeline...")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            pipeline_str = stdout.decode().strip()

            # Post-process: strip custom printer passes if present
            root = parse_pipeline(pipeline_str)

            def filter_passes(node):
                node.children = [c for c in node.children if c.name != "print"]
                for c in node.children:
                    filter_passes(c)

            filter_passes(root)

            self.query_one("#pipeline-editor", PipelineEditor).load_pipeline(
                root.to_string()
            )
            self.log_message(f"Loaded {level} preset.")

        else:
            self.log_message(f"[red]Failed to fetch {level} preset.[/red]")

    @on(Button.Pressed, ".preset-btn")
    def handle_preset(self, event: Button.Pressed) -> None:
        level = event.button.id.split("-")[1]
        self.run_worker(self.load_preset(level))

    @on(Tree.NodeSelected)
    def handle_node_selected(self, event: Tree.NodeSelected) -> None:
        node = event.node
        if node and hasattr(node, "data") and isinstance(node.data, PipelineNode):
            # Populate input with node name for potential modification
            self.query_one("#new-pass-name", Input).value = node.data.name

    def on_key(self, event) -> None:
        if event.key == "space":
            self.action_toggle_pass()
        elif event.key == "ctrl+up":
            self.handle_move_up()
        elif event.key == "ctrl+down":
            self.handle_move_down()


    @on(Button.Pressed, "#move-up-btn")
    def handle_move_up(self) -> None:
        tree = self.query_one("#pipeline-tree", Tree)
        node = tree.cursor_node
        if node and node.parent and node.parent.data:
            idx = node.parent.children.index(node)
            if idx > 0:
                # Swap in data model
                p_node = node.parent.data
                p_node.children[idx], p_node.children[idx - 1] = (
                    p_node.children[idx - 1],
                    p_node.children[idx],
                )
                # Rebuild and select
                target = node.data
                self.rebuild_node(node.parent)

                def restore_selection():
                    tree = self.query_one("#pipeline-tree", Tree)

                    # Traverse to find the new node that matches target
                    def find_node(n):
                        if n.data is target:
                            return n
                        for c in n.children:
                            res = find_node(c)
                            if res:
                                return res
                        return None

                    new_node = find_node(tree.root)
                    if new_node:
                        tree.select_node(new_node)
                        new_node.expand()

                self.call_after_refresh(restore_selection)

    @on(Button.Pressed, "#move-down-btn")
    def handle_move_down(self) -> None:
        tree = self.query_one("#pipeline-tree", Tree)
        node = tree.cursor_node
        if node and node.parent and node.parent.data:
            idx = node.parent.children.index(node)
            if idx < len(node.parent.children) - 1:
                # Swap in data model
                p_node = node.parent.data
                p_node.children[idx], p_node.children[idx + 1] = (
                    p_node.children[idx + 1],
                    p_node.children[idx],
                )
                # Rebuild and select
                target = node.data
                self.rebuild_node(node.parent)

                def restore_selection():
                    tree = self.query_one("#pipeline-tree", Tree)

                    # Traverse to find the new node that matches target
                    def find_node(n):
                        if n.data is target:
                            return n
                        for c in n.children:
                            res = find_node(c)
                            if res:
                                return res
                        return None

                    new_node = find_node(tree.root)
                    if new_node:
                        tree.select_node(new_node)
                        new_node.expand()

                self.call_after_refresh(restore_selection)

    @on(Button.Pressed, "#remove-pass-btn")
    def handle_remove(self) -> None:
        tree = self.query_one("#pipeline-tree", Tree)
        node = tree.cursor_node
        if node and node.parent and node.parent.data:
            idx = node.parent.children.index(node)
            node.parent.data.children.pop(idx)
            self.rebuild_node(node.parent)

    @on(Button.Pressed, "#add-pass-btn")
    def handle_add_pass(self) -> None:
        tree = self.query_one("#pipeline-tree", Tree)
        node = tree.cursor_node
        pass_name = self.query_one("#new-pass-name", Input).value
        
        if node and node.parent and node.parent.data and pass_name:
            # Insert after the currently selected node
            parent_node = node.parent
            children = parent_node.data.children
            try:
                idx = children.index(node.data)
                parent_node.data.children.insert(idx + 1, PipelineNode(pass_name))
            except ValueError:
                # Fallback if node not found in children
                parent_node.data.children.append(PipelineNode(pass_name))
            
            self.rebuild_node(parent_node)
            self.query_one("#new-pass-name", Input).value = ""
        elif tree.root.data and pass_name:
            # Add to root if nothing else is valid
            tree.root.data.children.append(PipelineNode(pass_name))
            self.rebuild_node(tree.root)
            self.query_one("#new-pass-name", Input).value = ""

    @on(Button.Pressed, "#modify-pass-btn")
    def handle_modify_pass(self) -> None:
        tree = self.query_one("#pipeline-tree", Tree)
        node = tree.cursor_node
        new_name = self.query_one("#new-pass-name", Input).value
        if node and node.data and new_name:
            node.data.name = new_name
            # Rebuild node to update label
            if node.parent:
                self.rebuild_node(node.parent)
            else:
                self.rebuild_node(node)

    def rebuild_node(self, tree_node, target_data=None):
        tree_node.remove_children()
        pipe_node = tree_node.data
        editor = self.query_one("#pipeline-editor", PipelineEditor)
        found_node = None
        for child in pipe_node.children:
            new_tree_node = tree_node.add(child.name, data=child)
            editor.build_tree(new_tree_node, child)
            if child is target_data:
                found_node = new_tree_node
        tree_node.expand_all()
        return found_node

    def refresh_files(self) -> None:
        # Refresh DirectoryTree
        try:
            tree = self.query_one("#source-tree", DirectoryTree)
            tree.reload()
        except:
            pass

        # Refresh SelectionList (Plugins)
        try:
            self._is_refreshing = True
            plugin_list = self.query_one("#plugin-list", SelectionList)

            files = sorted(Path("plugins").glob("*.cpp"))

            # Optimization: only refresh if the list of files changed or first load
            current_files = set(str(opt.value) for opt in plugin_list._options)
            new_files = set(str(p) for p in files)

            if current_files != new_files or self._first_load:
                new_options = []
                current_selected_vals = set(str(p) for p in self.selected_plugins)

                for p in files:
                    val = str(p)
                    # On first load, select all. Otherwise, preserve selection.
                    is_selected = (
                        True if self._first_load else val in current_selected_vals
                    )
                    new_options.append((p.name, val, is_selected))

                plugin_list.clear_options()
                plugin_list.add_options(new_options)

                if self._first_load:
                    self.selected_plugins = files
                    self._first_load = False
        finally:
            self._is_refreshing = False

    def log_message(self, message: str):
        for log_id in ("#log-view", "#status-log"):
            try:
                log_view = self.query_one(log_id, RichLog)
                log_view.write(message)
            except:
                pass

    @work(exclusive=True)
    async def run_process(self):
        if not self.selected_source:
            self.log_message("[red]Error: No source file selected![/red]")
            return

        # Clear logs
        for log_id in ("#log-view", "#status-log"):
            try:
                self.query_one(log_id, RichLog).clear()
            except:
                pass

        self.log_message(
            f"--- Starting Optimization Workflow at {datetime.now().strftime('%H:%M:%S')} ---"
        )

        clang_flags = self.query_one("#clang-flags", Input).value
        opt_pipeline = self.query_one(
            "#pipeline-editor", PipelineEditor
        ).get_pipeline_string()

        if not opt_pipeline:
            self.log_message(
                "[yellow]Warning: Pipeline is empty or all passes are disabled.[/yellow]"
            )

        # Determine if we need to compile
        if self.selected_source.suffix == ".ll":
            self.log_message(
                f"Skipping compilation for IR file: {self.selected_source.name}"
            )
            ir_file = self.selected_source
        else:
            # 1. Compile Source to IR
            ir_file = await self.compile_source(self.selected_source, clang_flags)
            if not ir_file:
                return

        # 2. Compile Plugins
        plugin_libs = []
        for p_src in self.selected_plugins:
            lib = await self.compile_plugin(p_src)
            if not lib:
                return
            plugin_libs.append(lib)

        # 3. Run Opt
        res = await self.run_opt(ir_file, plugin_libs, opt_pipeline)

        if res:
            self.save_manifest()
            # Auto-save pipeline to cache
            with open(CACHE_DIR / "pipeline.ll", "w") as f:
                f.write(opt_pipeline)
            self.log_message("[green]Pipeline auto-saved to .build_cache/pipeline.ll[/green]")
            self.log_message("[bold green]Workflow completed successfully![/bold green]")


    async def compile_source(self, src_path, flags):
        h = self.get_file_hash(src_path)
        strip_optnone = self.query_one("#strip-optnone", Checkbox).value
        cache_key = f"src_{src_path.name}_{hash(flags)}_{strip_optnone}"
        out_path = CACHE_DIR / f"{src_path.stem}.ll"

        clang = self.find_tool("clang++")
        cmd = [clang, "-S", "-emit-llvm"] + flags.split()
        if strip_optnone:
            cmd.extend(["-Xclang", "-disable-O0-optnone"])
        cmd.extend([str(src_path), "-o", str(out_path)])
        self.update_compile_commands(src_path, cmd)

        if self.manifest["files"].get(cache_key) == h and out_path.exists():
            self.log_message(f"Using cached IR for {src_path.name}")
            return out_path

        self.log_message(f"Compiling {src_path.name} to IR...")
        if await self.exec_cmd(cmd):
            # Post-process: strip noinline attributes if requested
            if strip_optnone:
                content = out_path.read_text()
                import re

                # Replace ' optnone' and ' noinline' attributes in function definitions
                content = re.sub(r"\b(noinline)\b", "", content)
                out_path.write_text(content)

            self.manifest["files"][cache_key] = h
            return out_path
        return None

    async def compile_plugin(self, p_src):
        h = self.get_file_hash(p_src)
        cache_key = f"plugin_{p_src.name}"
        out_path = CACHE_DIR / f"{p_src.stem}.so"

        llvm_config = self.find_tool("llvm-config")
        cxxflags = (
            subprocess.check_output([llvm_config, "--cxxflags"], text=True)
            .strip()
            .split()
        )
        ldflags = (
            subprocess.check_output([llvm_config, "--ldflags"], text=True)
            .strip()
            .split()
        )

        clang_cpp = self.find_tool("clang++")
        cmd = (
            [clang_cpp, "-shared", "-fPIC"]
            + cxxflags
            + [str(p_src)]
            + ldflags
            + ["-o", str(out_path)]
        )
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
            return out_path
        return None

    async def exec_cmd(self, cmd, log_stdout=True):
        self.log_message(f"[dim]Exec: {' '.join(cmd)}[/dim]")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if stdout and log_stdout:
            self.log_message(stdout.decode())
        if stderr and log_stdout:
            # Only show stderr if it's not the IR itself being misdirected
            self.log_message(f"[yellow]{stderr.decode()}[/yellow]")

        if proc.returncode != 0:
            self.log_message(
                f"[red]Command failed with exit code {proc.returncode}[/red]"
            )
            return False
        return True

    def find_tool(self, tool_name):
        try:
            selected_v = self.query_one("#llvm-version-select", Select).value
            if selected_v == Select.BLANK:
                selected_v = ""
        except:
            # If UI is not ready, use the first discovered version
            selected_v = self.available_versions[0][1] if hasattr(self, 'available_versions') else ""

        # Try selected version first
        name = f"{tool_name}{selected_v}"
        if shutil.which(name):
            return name

        # Fallback to any available version in our discovered list
        for _, v in self.available_versions:
            name = f"{tool_name}{v}"
            if shutil.which(name):
                return name
        
        return tool_name


import asyncio

if __name__ == "__main__":
    app = LLVMLabApp()
    app.run()
