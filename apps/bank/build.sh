#!/bin/bash

REGISTRY=10.43.67.161:5000/bank-app
paths=(entry-point login authorization verify-transaction transaction result)
languages=(python)      # java

for p in ${paths[@]}; do
    cd $p
    if [[ "$p" != "entry-point" && "$p" != "login" && "$p" != "transaction" && "$p" != "result" ]]; then
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
    else
        docker build -t="$REGISTRY/$p" .
        docker push "$REGISTRY/$p"
    fi
    cd ../
done
