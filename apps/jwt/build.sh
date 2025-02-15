#!/bin/bash

REGISTRY=10.43.67.161:5000/jwt-app
paths=(get-secret login)
languages=(python java)

for p in ${paths[@]}; do
    cd $p
    for l in ${languages[@]}; do
        cd $l
        if [[ "$l" == "java" ]]; then
            mvn compile jib:build -Dimage="$REGISTRY/$p/$l"
        else
            docker build -t="$REGISTRY/$p/$l" .
            docker push "$REGISTRY/$p/$l"
        fi
        cd ../
    done
    cd ../
done
