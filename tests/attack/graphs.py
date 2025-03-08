import os
import seaborn as sns
import matplotlib.pyplot as plt
import json
import pandas as pd

COMPARISON = 5
SIZE = (7, 5)
SIZE_RATION = SIZE[1] / COMPARISON


RESULTS_DIR = "results/"

CONCURRENCY = "singular"            # singular or multiple

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


def main():
    # This list will hold the results from all files
    all_results = {}

    # Iterate over items in the current directory
    for item in os.listdir('results/'):
        info = item.split('_')
        amount = int(info[1].split('-')[1])
        s = info[2].split('-')
        auth_conc = f"c{s[1]}" if s[0] == "auth" else f"v{s[1]}"
        s = info[3].split('-')
        verify_conc = f"c{s[1]}" if s[0] == "verify" else f"v{s[1]}"
        # if verify_conc > 4:
        #     continue

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
                # pod_results = read_results_pod(file_path)
                pod_results.extend(read_results_pod(file_path))
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
        
        # if item.startswith("test_amt-10_auth-1_verify-1"):
        #     for i in (r := all_results[amount][auth_conc][verify_conc]):
        #         if not r[i].get("pod_results"):
        #             print(i, r[i])

    # Now all_results holds the parsed data from each pod_result file.

    data = {
        "Test": [],
        "Relative frequency": [],
        "Time": []
    }
    # for amount in all_results:
    #     for auth in all_results[amount]:
    #         if CONCURRENCY == "singular" and auth != f"c{1}":
    #             continue
    #         if CONCURRENCY == "multiple" and auth == f"c{1}":
    #             continue
    #         for verify in all_results[amount][auth]:
    #             if amount == 100 and auth == f"c{1}" and verify != f"c{1}" and CONCURRENCY == "singular":
    #                 continue
    #             x = 0
    #             l = 1
    #             data["Time"].append([])
    #             for r in (c := all_results[amount][auth][verify]):
    #                 if 'pod_results' in c[r]:
    #                     if c[r]['pod_results']["body"].get("message") == "Transaction successful":
    #                         x += 1
    #                         if 'requests_trace' in c[r]:
    #                             data["Time"][-1].append(c[r]['pod_results']["time"] - c[r]['requests_trace']['start'])
    #                     l += 1
    #             data["Test"].append(f"Amount {amount}\nAuth {auth}\nVerify {verify}")
    #             data["Relative frequency"].append(x/l)
    #             print(x)
    #             # data.append(x/len(c)*100)
    for amount in all_results:
        for auth in all_results[amount]:
            print(f"{auth} -> {all_results[amount][auth].keys()}")
            if auth.startswith("c"):
                continue
            for verify in all_results[amount][auth]:
                if verify.startswith("c"):
                    continue
                x = 0
                l = 1
                data["Time"].append([])
                for r in (c := all_results[amount][auth][verify]):
                    if 'pod_results' in c[r]:
                        if c[r]['pod_results']["body"].get("message") == "Transaction successful":
                            x += 1
                            if 'requests_trace' in c[r]:
                                data["Time"][-1].append(c[r]['pod_results']["time"] - c[r]['requests_trace']['start'])
                        l += 1
                data["Test"].append(f"Amount {amount}\nAuth {auth}\nVerify {verify}")
                data["Relative frequency"].append(x/l)
                print(x)
    
    df = pd.DataFrame(data)
    sns.set_theme(rc={"figure.figsize": SIZE})
    ax = sns.scatterplot(data=data, x="Test", y="Relative frequency")
    
    for i, row in df.iterrows():
        # Get the x position corresponding to the categorical tick.
        # ax.get_xticks() returns the positions of the ticks, which should align with the order of your categories.
        xtick_positions = ax.get_xticks()
        # Assuming the categories are in order
        x_pos = xtick_positions[i]
        y_pos = row["Relative frequency"]
        # Add an offset to y to avoid overlapping the marker
        ax.text(x=x_pos, y=y_pos + 0.02, s=f"{y_pos:.3f}", ha='center', va='bottom', fontdict={"size": 12*SIZE_RATION})
    
    plt.ylim(0, 1)
    plt.title(f"Relative frequency of a successful attack with concurrency {'=' if CONCURRENCY == 'singular' else '>'} 1\n", fontdict={"size": 17*SIZE_RATION})
    
    ax.yaxis.label.set_fontsize(15*SIZE_RATION)
    ax.xaxis.label.set_fontsize(15*SIZE_RATION)
    ax.tick_params(labelsize=12*SIZE_RATION)
    plt.tight_layout()
    plt.savefig(f"concurrency_{CONCURRENCY}.pdf")

    plt.show()

if __name__ == "__main__":
    main()
