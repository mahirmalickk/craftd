#!/bin/bash
# Double-click this file in Finder to start Craftd (after the one-time setup in README.md).
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate
python -m craftd
