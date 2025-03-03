#!/bin/bash
# set -euo pipefail

##########################
# CONSTANTS – CONFIGURE THESE AS NEEDED
##########################
SSH_PASSWORD="olaadeus"                     # SSH password for the Kubernetes cluster machines
MACHINE_USER="ubuntu"                     # SSH user (assumed to have sudo privileges for reboot)
MACHINES=("10.255.30.127" "10.255.30.73" "10.255.30.147")  # IPs of the 3 Kubernetes machines
HELM_CHART_DIR="../../apps/sample-workflow/chart/"             # Path to the helm chart directory
REQUEST_COUNT=1500                                 # Number of consecutive curl requests per test cycle
WAIT_PERIOD=1                                    # Seconds to wait between each request
NAMESPACE="mofaas-sample-workflow"                       # Kubernetes namespace for helm chart deployment
RELEASE_NAME="sample-workflow"                      # Helm release name to be used for installation
ENTRY_URL="http://entry-point.mofaas-sample-workflow.10.255.30.127.sslip.io"  # URL to contact for test requests
WAIT_REBOOT=280                                  # Seconds to wait after rebooting the cluster machines

# Base directory to store test results (trace file and pod logs)
BASE_RESULT_DIR="./results"
mkdir -p "$BASE_RESULT_DIR"

##########################
# HELPER FUNCTIONS
##########################

# Wait until the only pod in the namespace has a name starting with "result"
wait_for_helm_ready() {
    versions=$1
    path=$2
    needed_pods=$(( versions * path + 2 ))
    echo "Waiting for helm install to be ready (only one pod starting with 'result')..."
    while true; do
        # mapfile -t pods < <(kubectl get pods -n "$NAMESPACE" --no-headers -o custom-columns=NAME:.metadata.name)
        number_pods=$(kubectl get pods -n $NAMESPACE | grep Running | wc | awk '{print $1}')
        if [[ $number_pods -eq $needed_pods ]]; then
            echo "Helm chart is ready."
            break
        else
            echo "Not the required number of pods yet (there are $number_pods pods). Retrying in 5 seconds..."
            sleep 5
        fi
    done
}

# Wait until no pods exist in the namespace (after helm uninstall)
wait_for_pods_termination() {
    echo "Waiting for all pods to be terminated in namespace '$NAMESPACE'..."
    while true; do
        remaining=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l)
        if [ "$remaining" -eq 0 ]; then
            echo "All pods terminated."
            break
        else
            echo "$remaining pod(s) still running. Waiting 5 seconds..."
            sleep 5
        fi
    done
}

# Wait until all cluster nodes are Ready
wait_for_cluster() {
    echo "Waiting for all cluster nodes to be Ready..."
    while true; do
        not_ready=$(kubectl get nodes | tail -n 3 | grep -v " Ready" | wc -l)
        if [ "$not_ready" -eq 0 ]; then
            echo "All cluster nodes are Ready."
            break
        else
            echo "Some nodes are not Ready. Waiting 10 seconds..."
            sleep 10
        fi
    done
}

# Reboot all machines via SSH (requires sshpass)
reboot_machines() {
    echo "Rebooting cluster machines..."
    for machine in "${MACHINES[@]}"; do
        echo "Rebooting machine $machine..."
        sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no "$MACHINE_USER@$machine" "sudo reboot" &
    done
    echo "Waiting $WAIT_REBOOT seconds for machines to reboot..."
    sleep "$WAIT_REBOOT"
}

main_task() {
    versions_per_function=$1
    path_size=$2
    concurrency=$3
    deployment_type=$4

    ##########################
    # 1. REBOOT CLUSTER MACHINES AND WAIT FOR CLUSTER TO BE READY
    ##########################
    reboot_machines
    wait_for_cluster

    # Create a unique directory for this test run (parameters in name)
    test_timestamp=$(date +%Y%m%d%H%M%S)
    test_dir="${BASE_RESULT_DIR}/test_versfunc-${versions_per_function}_pathsize-${path_size}_concurrency-${concurrency}_dt-${deployment_type}_${test_timestamp}"
    mkdir -p "$test_dir"
    echo "-------------------------------------------------------"
    echo "Starting test run with parameters:" 
    echo "  Versions per function: $versions_per_function"
    echo "  Path size: $path_size"
    echo "  Concurrency: $concurrency"
    echo "  Deployment type: $deployment_type"
    echo "  Test Directory: $test_dir"

    ##########################
    # 2. INSTALL HELM CHART WITH GIVEN PARAMETERS
    ##########################
    echo "Installing helm chart..."
    tmp_values_file=$(mktemp)
    cp "$HELM_CHART_DIR/values.yaml" "$tmp_values_file"
    yq eval ".multiVersionServices[0].deploymentType = \"$deployment_type\"" -i "$tmp_values_file"
    yq eval ".multiVersionServices[0].concurrency = $concurrency" -i "$tmp_values_file"
    yq eval ".multiVersionServices[0].pathSize = $path_size" -i "$tmp_values_file"
    yq eval ".multiVersionServices[0].versions = $versions_per_function" -i "$tmp_values_file"
    helm install "$RELEASE_NAME" "$HELM_CHART_DIR" -f "$tmp_values_file"

    # Wait until helm install is ready
    sleep 60
    wait_for_helm_ready $versions_per_function $path_size
    ./top.sh $NAMESPACE $test_dir $WAIT_PERIOD &
    top_pid=$!

    echo "Saving logs from pods during execution"
    pods_to_log=$(kubectl get pods -n "$NAMESPACE" --no-headers -o custom-columns=NAME:.metadata.name || true)
    for pod in $pods_to_log; do
        pod_log_file="${test_dir}/pod_${pod}_logs_pre.txt"
        echo "Saving logs for pod $pod to $pod_log_file"
        kubectl logs "$pod" -c user-container -n "$NAMESPACE" --follow > "$pod_log_file" &
    done

    ##########################
    # 3. PERFORM REQUESTS WITH CURL (TRACE SAVED)
    ##########################
    result_trace_file="${test_dir}/requests_trace.txt"
    echo "Recording request traces in $result_trace_file"
    echo "Test run parameters: Versions per function=$versions_per_function, Path size=$path_size, Concurrency=$concurrency, Deployment type: $deployment_type, Timestamp=$test_timestamp" > "$result_trace_file"
    echo "-------------------------------------------------------" >> "$result_trace_file"

    for (( i=1; i<=REQUEST_COUNT; i++ )); do
        req_start=$(date +%s.%N)
        echo "Request $i start: $req_start" >> "$result_trace_file"
        
        # Execute curl request and capture response
        response=$(curl --silent --data '{}' $ENTRY_URL -H 'Content-type: application/json')
        req_end=$(date +%s.%N)
        echo "Request $i end: $req_end" >> "$result_trace_file"
        echo "Response: $response" >> "$result_trace_file"
        echo "-------------------------------------------------------" >> "$result_trace_file"

        sleep "$WAIT_PERIOD"
    done

    # Stop top from getting more results
    kill -9 $top_pid

    ##########################
    # 4. SAVE POD LOGS BEFORE UNINSTALLING THE HELM RELEASE
    ##########################
    echo "Saving logs from pods"
    pods_to_log=$(kubectl get pods -n "$NAMESPACE" --no-headers -o custom-columns=NAME:.metadata.name || true)
    for pod in $pods_to_log; do
        pod_log_file="${test_dir}/pod_${pod}_logs.txt"
        echo "Saving logs for pod $pod to $pod_log_file"
        kubectl logs "$pod" -c user-container -n "$NAMESPACE" > "$pod_log_file"

        # Check if the pod has a previous instance and save its logs
        echo "Saving logs for previous instance of pod $pod" >> "$pod_log_file"
        kubectl logs "$pod" -c user-container -n "$NAMESPACE" --previous >> "$pod_log_file"
    done

    ##########################
    # 5. UNINSTALL THE HELM RELEASE AND WAIT FOR PODS TO TERMINATE
    ##########################
    echo "Uninstalling helm release '$RELEASE_NAME'"
    helm uninstall "$RELEASE_NAME"
    wait_for_pods_termination
    kubectl delete namespace $NAMESPACE &
    sleep 60
    kubectl delete namespace $NAMESPACE --force --grace-period=0
    sleep 60

    echo "Test run completed. Results saved in directory: $test_dir"
    echo "-------------------------------------------------------"
}


# vary the number of versions per function and concurrency
path_size=10
deployment_type=attack
for vpf in {1..10}; do
    for concurrency in $(seq 1 $vpf); do
        main_task $vpf $path_size $concurrency $deployment_type
    done
done

# vary the path size
vpf=10
for deployment_type in attack normal; do
    if [[ $deployment_type == "attack" ]]; then
        vpf=10
    else
        vpf=1
    fi
    for path_size in {1..10}; do
        for concurrency in 1 10; do
            if [[ $concurrency -gt 1 && $deployment_type == "normal" ]]; then
                continue
            fi
            main_task $vpf $path_size $concurrency $deployment_type
        done
    done
done

echo "All tests completed."
