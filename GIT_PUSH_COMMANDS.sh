#!/bin/bash
# Commands to commit and push the WebSocket integration

cd /benoit_home/projects/ha-inventree

echo "=== Checking git status ==="
git status

echo ""
echo "=== Adding new files ==="
git add custom_components/inventree/websocket_client.py
git add custom_components/inventree/coordinator_v2.py

echo ""
echo "=== Adding modified files ==="
git add custom_components/inventree/__init__.py
git add custom_components/inventree/const.py
git add custom_components/inventree/config_flow.py

echo ""
echo "=== Committing changes ==="
git commit -F COMMIT_MESSAGE.txt

echo ""
echo "=== Pushing to GitHub ==="
git push

echo ""
echo "=== Done! ==="
echo "Your WebSocket integration has been pushed to GitHub!"

