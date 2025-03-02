#!/bin/bash

REGISTRY=10.43.67.161:5000/sample-workflow
paths=(entry-point function result)

for p in ${paths[@]}; do
    cd $p
    docker build -t="$REGISTRY/$p" .
    docker push "$REGISTRY/$p"
    cd ../
done
