#!/bin/bash

cd /home/idg_rasp1/marginx || exit 1

source .venv/bin/activate

exec python3 tools/marginxGUI.py \
    --seconds 60 \
    --shift-period 0.001 \
    --rot-period 0.020

