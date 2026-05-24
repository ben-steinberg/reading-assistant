#!/bin/bash
# Double-click this file to start the Reading Assistant server

cd ~/Desktop/Reading-Assistant
source .venv/bin/activate
uvicorn main:app --reload
