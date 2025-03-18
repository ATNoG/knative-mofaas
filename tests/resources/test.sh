#!/bin/bash
# set -euo pipefail

##########################
# CONSTANTS – CONFIGURE THESE AS NEEDED
##########################
SSH_PASSWORD="olaadeus"                     # SSH password for the Kubernetes cluster machines
MACHINE_USER="ubuntu"                     # SSH user (assumed to have sudo privileges for reboot)
MACHINES=("10.255.30.133" "10.255.30.120" "10.255.30.35")  # IPs of the 3 Kubernetes machines
HELM_CHART_DIR="../../apps/bank/chart/"             # Path to the helm chart directory
REQUEST_COUNT=1500                                 # Number of consecutive curl requests per test cycle
WAIT_PERIOD=1                                    # Seconds to wait between each request
NAMESPACE="mofaas-bank-app"                       # Kubernetes namespace for helm chart deployment
RELEASE_NAME="bank"                      # Helm release name to be used for installation
ENTRY_URL="http://entry-point.mofaas-bank-app.10.255.30.133.sslip.io"  # URL to contact for test requests
WAIT_REBOOT=280                                  # Seconds to wait after rebooting the cluster machines
VERSIONS=(python java js go php attack)
amount=10

# Base directory to store test results (trace file and pod logs)
BASE_RESULT_DIR="./results"
mkdir -p "$BASE_RESULT_DIR"

##########################
# HELPER FUNCTIONS
##########################

# Wait until the only pod in the namespace has a name starting with "result"
wait_for_helm_ready() {
    echo "Waiting for helm install to be ready (only one pod starting with 'result')..."
    while true; do
        # mapfile -t pods < <(kubectl get pods -n "$NAMESPACE" --no-headers -o custom-columns=NAME:.metadata.name)
        number_pods=$(kubectl get pods -n mofaas-bank-app | grep Running | wc | awk '{print $1}')
        if [[ $number_pods -eq 14 ]]; then
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

##########################
# MAIN LOOP: TEST RUNS WITH DIFFERENT PARAMETERS
##########################

# We now run independent test cycles for each amount (10 and 100), combined with each combination
# of authorization and verify-transaction concurrency (ranging from 1 to 5).
# for auth_test in ${VERSIONS[@]}; do
#     for verify_test in ${VERSIONS[@]}; do
#         for concurrency_auth in 1 5; do
#             for concurrency_verify in 1 5; do
for auth_test in attack; do
    for verify_test in attack; do
        for concurrency_auth in 5; do
            for concurrency_verify in 1; do
                if [[ $concurrency_auth -eq 5 ]] && [[ $auth_test != "attack" ]]; then
                    continue
                fi
                if [[ $concurrency_verify -eq 5 ]] && [[ $verify_test != "attack" ]]; then
                    continue
                fi

                ##########################
                # 1. REBOOT CLUSTER MACHINES AND WAIT FOR CLUSTER TO BE READY
                ##########################
                reboot_machines
                wait_for_cluster

                # Create a unique directory for this test run (parameters in name)
                test_timestamp=$(date +%Y%m%d%H%M%S)
                test_dir="${BASE_RESULT_DIR}/test_amt-${amount}_auth-${auth_test}_verify-${verify_test}_concurrency-${concurrency_auth}_concurrency-${concurrency_verify}_${test_timestamp}"
                mkdir -p "$test_dir"
                echo "-------------------------------------------------------"
                echo "Starting test run with parameters:" 
                echo "  Amount: $amount"
                echo "  Authorization version: $auth_test"
                echo "  Verify-transaction version: $verify_test"
                echo "  Test Directory: $test_dir"
                echo "  Concurency auth: $concurrency_auth"
                echo "  Concurency verify: $concurrency_verify"

                ##########################
                # 2. INSTALL HELM CHART WITH GIVEN PARAMETERS
                ##########################
                echo "Installing helm chart..."
                tmp_values_file=$(mktemp)
                cp "$HELM_CHART_DIR/values.yaml" "$tmp_values_file"
                yq eval ".multiVersionServices[0].deploymentType = \"$auth_test\"" -i "$tmp_values_file"
                yq eval ".multiVersionServices[1].deploymentType = \"$verify_test\"" -i "$tmp_values_file"
                yq eval ".multiVersionServices[0].concurrency = $concurrency_auth" -i "$tmp_values_file"
                yq eval ".multiVersionServices[1].concurrency = $concurrency_verify" -i "$tmp_values_file"
                helm install "$RELEASE_NAME" "$HELM_CHART_DIR" -f "$tmp_values_file"

                # Wait until helm install is ready
                sleep 60
                wait_for_helm_ready
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
                echo "Test run parameters: Amount=$amount, Auth version=$auth_test, Verify version=$verify_test, Timestamp=$test_timestamp" > "$result_trace_file"
                echo "-------------------------------------------------------" >> "$result_trace_file"

                token=$(curl -s -D - --data '{"username": "admin", "password": "olaadeus"}' http://login.mofaas-bank-app.10.255.30.133.sslip.io -H "Content-Type: application/json" | grep -i authorization | awk '{print $3}' | tr -d '\r')
                for (( i=1; i<=REQUEST_COUNT; i++ )); do
                    req_start=$(date +%s.%N)
                    echo "Request $i start: $req_start" >> "$result_trace_file"
                    
                    # Build JSON payload
                    payload="{\"destination_client\": \"attacker\", \"amount\": $amount}"
                    # Build curl headers
                    headers=(-H "Authorization: Bearer $token" -H "Content-Type: application/json")

                    # Execute curl request and capture response
                    response=$(curl --silent --data "$payload" "$ENTRY_URL" "${headers[@]}")
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

                echo "Test run completed. Results saved in directory: $test_dir"
                echo "-------------------------------------------------------"
            done
        done
    done
done

echo "All tests completed."
