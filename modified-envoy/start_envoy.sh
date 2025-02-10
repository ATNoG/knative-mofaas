#!/bin/bash

# ulimit -n {{ pillar.get('envoy_max_open_files', '102400') }}
# sysctl fs.inotify.max_user_watches={{ pillar.get('envoy_max_inotify_watches', '524288') }}

exec /usr/local/bin/envoy -c /etc/envoy/envoy.yaml --log-level trace --restart-epoch $RESTART_EPOCH # --service-cluster {{ grains['cluster_name'] }} --service-node {{ grains['service_node'] }} --service-zone {{ grains.get('ec2_availability-zone', 'unknown') }}
