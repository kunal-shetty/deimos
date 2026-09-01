#!/bin/bash

# Deimos Installation Script
# This script sets up a local virtual environment for Deimos and symlinks the executable.

set -e

echo "Installing Deimos..."

# 1. Create the Deimos home directory
DEIMOS_HOME="$HOME/.deimos"
mkdir -p "$DEIMOS_HOME"

# 2. Set up a private virtual environment
echo "Creating virtual environment in $DEIMOS_HOME/venv..."
if command -v python3 >/dev/null 2>&1; then
    PYTHON_EXE="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_EXE="python"
else
    echo "Error: Python not found. Please install Python 3."
    exit 1
fi

$PYTHON_EXE -m venv "$DEIMOS_HOME/venv"

# 3. Install Deimos and dependencies
echo "Installing dependencies..."
"$DEIMOS_HOME/venv/bin/pip" install --upgrade pip
# Install the current directory as a package
# We assume this script is run from the root of the repo or that the repo is cloned.
# If the script is hosted remotely, the installer should clone the repo first.
if [ -f "pyproject.toml" ]; then
    "$DEIMOS_HOME/venv/bin/pip" install .
else
    echo "Error: pyproject.toml not found. Please run this script from the Deimos root directory."
    exit 1
fi

# 4. Symlink the executable to a directory in the PATH
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"

echo "Creating symlink in $BIN_DIR..."
ln -sf "$DEIMOS_HOME/venv/bin/deimos" "$BIN_DIR/deimos"

# 5. Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo ""
    echo "Warning: $BIN_DIR is not in your PATH."
    echo "Please add the following line to your .bashrc or .zshrc:"
    echo "export PATH=\"$BIN_DIR:\$PATH\""
    echo ""
fi

echo "Deimos installation complete! You can now run 'deimos assemble' from anywhere."
