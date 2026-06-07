#!/bin/bash
cd /home/fabien/tasky
git pull
sudo systemctl restart tasky
echo "Tasky mis à jour !"
