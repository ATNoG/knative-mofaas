#!/bin/bash

#!/bin/bash

REGISTRY=ghcr.io/atnog/knative-mofaas
paths=(egress-proxy function-chooser init-iptables modified-envoy)

for p in ${paths[@]}; do
    cd $p
        
        docker build -t="$REGISTRY/$p" .
        docker push "$REGISTRY/$p"
    cd ../
done

