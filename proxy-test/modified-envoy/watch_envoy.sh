#!/bin/sh
while true; do
    inotifywait -e modify,create,delete /etc/envoy/envoy.yaml
    echo "Config changed, reloading Envoy..."
    kill -HUP $(ps ax | grep python3 | awk '{print $1}' | head -n 1)
done
