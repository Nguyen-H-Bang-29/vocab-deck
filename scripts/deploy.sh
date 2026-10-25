#!/usr/bin/env bash
set -euo pipefail

uv sync
fly deploy
