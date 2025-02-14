#!/bin/bash

REGISTRY=10.43.67.161:5000/jwt-app
paths=(get-secret login)
languages=(python)

for p in ${paths[@]}; do
    cd $p
    for l in ${languages[@]}; do
        cd $l
        docker build -t="$REGISTRY/$p/$l" .
        docker push "$REGISTRY/$p/$l"
        cd ../
    done
    cd ../
done
