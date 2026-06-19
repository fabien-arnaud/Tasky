#!/bin/bash
BRANCH=$(git branch --show-current)
echo "Deploying branch: $BRANCH"
ssh fabien@51.15.190.170 "cd /home/fabien/tasky && git fetch origin && git reset --hard origin/$BRANCH && sudo systemctl restart tasky && echo 'Done: $BRANCH'"
