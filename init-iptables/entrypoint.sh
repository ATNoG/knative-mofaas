#!/bin/sh

iptables -t nat -P PREROUTING ACCEPT
iptables -t nat -P INPUT ACCEPT
iptables -t nat -P OUTPUT ACCEPT
iptables -t nat -P POSTROUTING ACCEPT
iptables -t nat -N ISTIO_OUTPUT
iptables -t nat -N ISTIO_REDIRECT
iptables -t nat -A OUTPUT -p tcp -j ISTIO_OUTPUT
# iptables -t nat -A ISTIO_OUTPUT ! -d 127.0.0.1/32 -o lo -j ISTIO_REDIRECT

# Ignore traffic from the envoy container
iptables -t nat -A ISTIO_OUTPUT -m owner --uid-owner 101 -j RETURN
iptables -t nat -A ISTIO_OUTPUT -m owner --gid-owner 101 -j RETURN

# Ignore traffic from the queue-proxy container
iptables -t nat -A ISTIO_OUTPUT -m owner --uid-owner 65532 -j RETURN
iptables -t nat -A ISTIO_OUTPUT -m owner --gid-owner 65532 -j RETURN

iptables -t nat -A ISTIO_OUTPUT -d 127.0.0.1/32 -j RETURN
iptables -t nat -A ISTIO_OUTPUT -j ISTIO_REDIRECT
iptables -t nat -A ISTIO_REDIRECT -p tcp -j REDIRECT --to-ports 10000
