#!/bin/sh

sh watch_envoy.sh &

python3 hot-restarter.py start_envoy.sh
