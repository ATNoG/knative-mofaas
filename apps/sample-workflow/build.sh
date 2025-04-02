#!/bin/bash

REGISTRY=ghcr.io/atnog/knative-mofaas/sample-workflow
paths=(entry-point function result)

for p in ${paths[@]}; do
    cd $p
    docker build -t="$REGISTRY/$p" .
    docker push "$REGISTRY/$p"
    cd ../
done
