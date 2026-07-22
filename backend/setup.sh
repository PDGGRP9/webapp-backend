#!/usr/bin/env bash
# Create a virtual environment and install requirements (Django)

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

echo "Done. Activate with: source venv/bin/activate"