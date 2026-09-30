#!/bin/bash
SCRIPT_DIR=/opt/downdetector-zabbix
source ${SCRIPT_DIR}/venv/bin/activate
xvfb-run --auto-servernum --server-args='-screen 0 1920x1080x24' python3 ${SCRIPT_DIR}/downdetector_collector.py "$@"
