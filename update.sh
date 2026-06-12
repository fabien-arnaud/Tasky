#!/bin/bash
cd /home/fabien/tasky
git fetch origin
git reset --hard origin/main
sudo systemctl restart tasky
echo "Tasky mis à jour !"
