#!/bin/bash

kubectl patch clusterrole knative-eventing-webhook \
 --type='json' \
 -p='[{"op": "add", "path": "/rules/-", "value": {"apiGroups": ["mofaas.atnog"], "resources": ["mofaasfunctions"], "verbs": ["get", "list", "watch"]}}]'
