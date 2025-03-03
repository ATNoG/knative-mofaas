#!/bin/bash

NAMESPACE=$1
TEST_DIR=$2
WAIT_PERIOD=$3

while true; do
    echo Top at $(date +%s.%N) >> $TEST_DIR/top.txt
    kubectl top pods --containers -n $NAMESPACE >> $TEST_DIR/top.txt
    echo "-------------------------------------------------------" >> $TEST_DIR/top.txt
    sleep $WAIT_PERIOD
done
