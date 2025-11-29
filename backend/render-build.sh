#!/usr/bin/env bash
# Render build script for OCR FEM Backend

echo "Installing system dependencies..."

# Install poppler-utils for pdf2image
apt-get update
apt-get install -y poppler-utils

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Build complete!"
