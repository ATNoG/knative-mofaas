import os
import seaborn as sns
import matplotlib.pyplot as plt
import json
import pandas as pd

COMPARISON = 5
SIZE = (7, 5)
SIZE_RATION = SIZE[1] / COMPARISON


RESULTS_DIR = "results/"

def read_results_pod(file_path):
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
            "body": body,
            "time": float(content[headers_marker - 18 - 28 - 16:headers_marker - 18 - 28])
        })
            
        pos = next_index_body
    return results


def read_requests_trace(file_path):
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
            print(file_path)

    return results


def sort_dict(d):
    """Recursively sort the keys of a dictionary."""
    if isinstance(d, dict):
        return {k: sort_dict(d[k]) if isinstance(d[k], dict) else d[k] for k in sorted(d)}
    return d


def main():
    # This list will hold the results from all files
    all_results = {}

    # Iterate over items in the current directory
    for item in os.listdir('results/'):
        info = item.split('_')
        versfunc = int(info[1].split('-')[1])
        pathsize = int(info[2].split('-')[1])
        concurrency = int(info[3].split('-')[1])
        dt = info[4].split('-')[1]
        print(dt)
        # if concurrency > 4:
        #     continue

        if versfunc not in all_results:
            all_results[versfunc] = {}
        if pathsize not in all_results[versfunc]:
            all_results[versfunc][pathsize] = {}
        if concurrency not in all_results[versfunc][pathsize]:
            all_results[versfunc][pathsize][concurrency] = {}
        if dt not in all_results[versfunc][pathsize][concurrency]:
            all_results[versfunc][pathsize][concurrency][dt] = {}

        pod_results = []

        print(item)
        # Look for files that start with 'pod_result'
        for filename in os.listdir(os.path.join(RESULTS_DIR, item)):
            file_path = os.path.join(RESULTS_DIR, item, filename)
            if filename.startswith("pod_result"):
                # pod_results = read_results_pod(file_path)
                pod_results.extend(read_results_pod(file_path))
            if filename == "requests_trace.txt":
                for i in (r := read_requests_trace(file_path)):
                    all_results[versfunc][pathsize][concurrency][dt][i] = {
                        "requests_trace": r[i]
                    }
                    
        for p in pod_results:
            _id = p["headers"]["Ce-Id"]
            if _id not in all_results[versfunc][pathsize][concurrency][dt]:
                all_results[versfunc][pathsize][concurrency][dt][_id] = {}
            all_results[versfunc][pathsize][concurrency][dt][_id]["pod_results"] = p
        
    
        
        # if item.startswith("test_amt-10_auth-1_verify-1"):
        #     for i in (r := all_results[versfunc][pathsize][concurrency]):
        #         if not r[i].get("pod_results"):
        #             print(i, r[i])

    # Now all_results holds the parsed data from each pod_result file.

    all_results = sort_dict(all_results)
    data = {
        "Versions per function": [],
        "Execution time (s)": [],
        "Path Size": [],
        "Concurrency": []
    }
    for versfunc in all_results:
        for pathsize in all_results[versfunc]:
            if pathsize != 5:
                continue
            for concurrency in all_results[versfunc][pathsize]:
                for dt in all_results[versfunc][pathsize][concurrency]:
                    if dt == "normal":
                        continue
                    for r in (c := all_results[versfunc][pathsize][concurrency][dt]):
                        if 'requests_trace' in c[r]:
                            if 'pod_results' in c[r]:
                                data["Execution time (s)"].append(c[r]['pod_results']["time"] - c[r]['requests_trace']['start'])
                            # data["Execution time (s)"].append(c[r]['requests_trace']['stop'] - c[r]['requests_trace']['start'])
                                data["Versions per function"].append(versfunc)      # \nConcurrency {concurrency}
                                data["Concurrency"].append(concurrency)
                                data["Path Size"].append(pathsize)
    
    # all_results = sort_dict(all_results)
    # data = {
    #     "Protection": [],            # concurrency 5
    #     "Time": [],
    #     "Path Size": [],
    # }
    # for versfunc in all_results:
    #     if versfunc != 5 and versfunc != 1:
    #         continue
    #     for pathsize in all_results[versfunc]:
    #         for concurrency in all_results[versfunc][pathsize]:
    #             if concurrency != 5 and concurrency != 1:
    #                 continue
    #             print(concurrency)
    #             for dt in all_results[versfunc][pathsize][concurrency]:
    #                 # if dt == "attack" and concurrency == 1:
    #                 #     continue
    #                 for r in (c := all_results[versfunc][pathsize][concurrency][dt]):
    #                     if 'requests_trace' in c[r]:
    #                         if 'pod_results' in c[r]:
    #                             data["Time"].append(c[r]['pod_results']["time"] - c[r]['requests_trace']['start'])
    #                     # if 'requests_trace' in (r := all_results[versfunc][pathsize][concurrency][dt]):
    #                         # data["Time"][-1].append(c[r]['pod_results']["time"] - c[r]['requests_trace']['start'])
    #                             # data["Time"].append(c[r]['requests_trace']['stop'] - c[r]['requests_trace']['start'])
    #                         # data["Test"].append(f"Versions per function {versfunc}\nDeployment type {dt}\nConcurrency {concurrency}")   
    #                             data["Protection"].append(f"With MoFaaS and Concurrency = {concurrency}" if dt == "attack" else "Without MoFaaS")
    #                             data["Path Size"].append(pathsize)

    sns.set_theme(rc={"figure.figsize": SIZE})
    ax = sns.pointplot(data=data, x="Versions per function", y="Execution time (s)", hue="Concurrency", linestyle="none", palette=sns.color_palette("colorblind"))
    # ax = sns.pointplot(data=data, x="Path Size", y="Time", hue="Protection", linestyle="none", palette=sns.color_palette("colorblind"))
    print(ax.get_lines()[0].get_data())
    for i in ax.get_lines():
        print(i.get_data())

    plt.ylim(0, 0.9)
    plt.title(f"Execution time varying the path size and concurrency", fontdict={"size": 17 * SIZE_RATION})
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True)

    ax.yaxis.label.set_fontsize(15*SIZE_RATION)
    ax.xaxis.label.set_fontsize(15*SIZE_RATION)
    ax.tick_params(labelsize=12*SIZE_RATION)
    plt.tight_layout()
    plt.savefig(f"concurrency_{CONCURRENCY}.pdf")

    plt.show()

if __name__ == "__main__":
    main()
