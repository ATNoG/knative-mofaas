import os
import re
import json

RESULTS_DIR = "results/"

def read_results_pod(file_name):
    results = []
    with open(file_path, 'r') as f:
        content = f.read()
                
    pos = 0
    while pos < len(content):
        # Locate the "HEADERS" marker
        headers_marker = content.find("HEADERS", pos)
        if headers_marker == -1:
            break
        # Locate the first '{' after "HEADERS"
        header_start = content.find('{', headers_marker)
        if header_start == -1:
            break

        try:
            headers, next_index = json.JSONDecoder().raw_decode(content, header_start)
        except Exception as e:
            headers = {}
            next_index = header_start + 1

        # Locate the "BODY" marker after the headers JSON
        body_marker = content.find("BODY", next_index)
        if body_marker == -1:
            break
        # Locate the first '{' after "BODY"
        body_start = content.find('{', body_marker)
        if body_start == -1:
            break

        try:
            body, next_index_body = json.JSONDecoder().raw_decode(content, body_start)
        except Exception as e:
            body = {}
            next_index_body = body_start + 1

        results.append({
            "headers": headers,
            "body": body
        })
            
        pos = next_index_body
    return results


def read_requests_trace(file_name):
    results = {}
    with open(file_path, 'r') as f:
        content = f.read()
    for result in content.split("\n-------------------------------------------------------\n")[1:5000]:
        try:
            lines = result.split("\n")
            response = json.loads(lines[2].split('Response: ')[1])
            results[response['id']] = {
                "response": response,
                "start": float(lines[0].split("start: ")[1]),
                "stop": float(lines[1].split("end: ")[1]),
                "number": int(lines[1].split(' ')[1])
            }
        except Exception as e:
            print("Hmmm")
            print(file_name)

    return results
    
# This list will hold the results from all files
all_results = {}

# Iterate over items in the current directory
for item in os.listdir('results/'):
    info = item.split('_')
    amount = int(info[1].split('-')[1])
    auth_conc = int(info[2].split('-')[1])
    verify_conc = int(info[3].split('-')[1])
    if verify_conc > 4:
        continue

    if amount not in all_results:
        all_results[amount] = {}
    if auth_conc not in all_results[amount]:
        all_results[amount][auth_conc] = {}
    if verify_conc not in all_results[amount][auth_conc]:
        all_results[amount][auth_conc][verify_conc] = {}
        
    pod_results = []

    print(item)
    # Look for files that start with 'pod_result'
    for filename in os.listdir(os.path.join(RESULTS_DIR, item)):
        file_path = os.path.join(RESULTS_DIR, item, filename)
        if filename.startswith("pod_result"):
            pod_results = read_results_pod(file_path)
        elif filename == "requests_trace.txt":
            for i in (r := read_requests_trace(file_path)):
                all_results[amount][auth_conc][verify_conc][i] = {
                    "requests_trace": r[i]
                }
    
    for p in pod_results:
        _id = p["headers"]["Ce-Id"]
        if _id not in all_results[amount][auth_conc][verify_conc]:
            all_results[amount][auth_conc][verify_conc][_id] = {}
        all_results[amount][auth_conc][verify_conc][_id]["pod_results"] = p
    
    if item == "test_amt-100_auth-1_verify-4_20250226135603":
        for i in (r := all_results[amount][auth_conc][verify_conc]):
            if not r[i].get("pod_results"):
                print(i, r[i])

# Now all_results holds the parsed data from each pod_result file.

# x = 0
# for r in (c := all_results[100][1][4]):
#     if r["body"].get("message") == "Transaction successful":
#         x += 1
# print(x)
# print(len(c))
