#!/usr/bin/env bash
# Диагностика: почему Акира не слышит голос и не переключается на Ollama.
cd "$(dirname "$0")"
source .venv/bin/activate
python check.py
