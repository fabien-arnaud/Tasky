#!/bin/bash
cd /home/fabien/tasky/app
git fetch origin
git reset --hard origin/main
sudo systemctl restart tasky tasky-yoan tasky-davy
echo "Tasky mis à jour (fabien, yoan, davy) !"
