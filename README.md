# LLVM IR Lab

A TUI-based dashboard for orchestrating LLVM IR experimentation and optimization.

## Features
- **Project Lab**: Organize and compile C++ source files and custom LLVM pass plugins.
- **TUI Dashboard**: An interactive interface to manage compilation, optimization pipelines, and view outputs.
- **Pipeline Editor**: Visual, hierarchical editor for LLVM optimization passes with support for O0-Os presets.
- **Incremental Builds**: Efficient caching of compiled IR and plugin libraries.
- **IDE Integration**: Automatically updates `compile_commands.json` for IDE IntelliSense support.
- **IR Analysis**: Full-screen IR viewer with syntax highlighting and detailed logging.

## Getting Started

### Prerequisites
- Python 3.12+
- Clang/LLVM toolchain installed

### Running the Dashboard
The dashboard uses a bash wrapper (`llvm-lab`) that automatically sets up a virtual environment and installs dependencies (`textual`, `rich`).

```bash
./llvm-lab
```

## Dashboard Layout

### CONFIG Tab
- **Left Sidebar**: 
  - Select C++ source files (files in `code/`).
  - Select active LLVM pass plugins (files in `plugins/`).
- **Center Pipeline Editor**: 
  - Hierarchical tree to view and edit optimization passes.
  - Load standard presets (**O0** through **Os**).
  - Modify pass names or toggle activation.
- **Right Panel**:
  - **Clang Flags**: Customize compilation settings.
  - **Strip optnone/noinline**: Checkbox to clean up `-O0` generated IR.
  - **Run Optimization**: Execute the workflow.
  - **Status Log**: Live updates on build progress and errors.

### IR VIEWER Tab
Displays the resulting optimized IR. Use this to analyze the effects of your pipeline.

### DETAILED LOGS Tab
Contains the full, raw output from Clang and Opt for advanced troubleshooting.

## Controls & Shortcuts

| Action | Shortcut |
| :--- | :--- |
| **Quit** | `q` |
| **Run Workflow** | `r` |
| **Toggle Pass State** | `Space` |
| **Move Pass Up** | `Ctrl+Up` |
| **Move Pass Down** | `Ctrl+Down` |
| **Select Pass/Source** | Mouse Click |

*Note: You can also use the buttons in the interface for reordering and adding passes.*

## Incremental Builds
The tool tracks file modifications in `.build_cache/`. It will only recompile source files, plugins, or perform optimizations if the underlying files or flags have changed.
