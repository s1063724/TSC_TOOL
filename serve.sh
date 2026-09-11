#!/bin/bash
# Foreground launcher for testing. For 24/7 use, prefer systemd service:
#   systemctl --user start dispatch-generator
cd "$(dirname "$0")"
echo "Open: http://$(hostname -I | awk '{print $1}'):9000/"
echo "Ctrl-C to stop. For background, use: nohup python3 app.py > /tmp/flask.log 2>&1 &"
exec python3 app.py
