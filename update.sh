#!/bin/bash
cd /home/fabien/tasky
git fetch origin
git reset --hard origin/main
sudo systemctl restart tasky tasky-yoan tasky-davy
echo "Tasky mis à jour (fabien, yoan, davy) !"
