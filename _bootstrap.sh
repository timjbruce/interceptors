#!/usr/bin/env bash
# Sourced by the run scripts: cd to the repo root and, on first use, create the
# venv and install deps. After editing requirements.txt, run `rm -rf .venv`.
cd "$(dirname "${BASH_SOURCE[0]}")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/python -m pip install -q -r requirements.txt
fi
