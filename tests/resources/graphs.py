import os
import seaborn as sns
import matplotlib.pyplot as plt
import json
import pandas as pd

COMPARISON = 5
SIZE = (7, 5)
SIZE_RATION = SIZE[1] / COMPARISON


RESULTS_DIR = "results/"
RESULT = "CPU"  # Memory or CPU
MAX_ITERATIONS = 1000

def read_results_pod(file_path):
    results = []
    with open(file_path, "r") as f:
        content = f.read()

    pos = 0
    while pos < len(content):
        # Locate the "HEADERS" marker
        headers_marker = content.find("HEADERS", pos)
        if headers_marker == -1:
            break
        # Locate the first '{' after "HEADERS"
        header_start = content.find("{", headers_marker)
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
        body_start = content.find("{", body_marker)
        if body_start == -1:
            break

        try:
            body, next_index_body = json.JSONDecoder().raw_decode(content, body_start)
        except Exception as e:
            body = {}
            next_index_body = body_start + 1

        results.append(
            {
                "headers": headers,
                "body": body,
                "time": float(
                    content[headers_marker - 18 - 28 - 16 : headers_marker - 18 - 28]
                ),
            }
        )

        pos = next_index_body
    return results[-MAX_ITERATIONS:]


def read_requests_trace(file_path):
    results = {}
    with open(file_path, "r") as f:
        content = f.read()
    for result in content.split(
        "\n-------------------------------------------------------\n"
    )[1:5000]:
        try:
            lines = result.split("\n")
            response = json.loads(lines[2].split("Response: ")[1])
            results[response["id"]] = {
                "response": response,
                "start": float(lines[0].split("start: ")[1]),
                "stop": float(lines[1].split("end: ")[1]),
                "number": int(lines[1].split(" ")[1]),
            }
        except Exception as e:
            print("Hmmm")
            print(file_path)

    return dict(list(results.items())[-MAX_ITERATIONS:])


def read_top(file_path):
    results = []
    with open(file_path, "r") as f:
        content = f.read()
    for result in content.split(
        "\n-------------------------------------------------------\n"
    ):
        lines = result.split("\n")
        if not lines[0]:
            break
        results.append(
            {
                "time": float(lines[0].split(" at ")[1]),
                "top": {},
            }
        )
        for l in lines[2:]:
            if not l:
                break
            info = l.split()
            info[0] = info[0][: info[0].find("deployment") - 7]
            if info[0] not in results[-1]["top"]:
                results[-1]["top"][info[0]] = {}
            results[-1]["top"][info[0]][info[1]] = {"cpu": info[2], "mem": info[3]}
    return results[-MAX_ITERATIONS:]


def sort_dict(d):
    """Recursively sort the keys of a dictionary."""
    if isinstance(d, dict):
        return {
            k: sort_dict(d[k]) if isinstance(d[k], dict) else d[k] for k in sorted(d)
        }
    return d


def main():
    # This list will hold the results from all files
    all_results = {}

    # Iterate over items in the current directory
    for item in os.listdir("results/"):
        info = item.split("_")
        auth_conc = info[2].split("-")[1]
        verify_conc = info[3].split("-")[1]
        concurrency1 = info[4].split("-")[1]
        concurrency2 = info[5].split("-")[1]

        if auth_conc not in all_results:
            all_results[auth_conc] = {}
        if verify_conc not in all_results[auth_conc]:
            all_results[auth_conc][verify_conc] = {}
        if concurrency1 not in all_results[auth_conc][verify_conc]:
            all_results[auth_conc][verify_conc][concurrency1] = {}
        if concurrency2 not in all_results[auth_conc][verify_conc][concurrency1]:
            all_results[auth_conc][verify_conc][concurrency1][concurrency2] = {}

        print(item)
        # Look for files that start with 'pod_result'
        for filename in os.listdir(os.path.join(RESULTS_DIR, item)):
            file_path = os.path.join(RESULTS_DIR, item, filename)
            if filename == "top.txt":
                all_results[auth_conc][verify_conc][concurrency1][concurrency2] = read_top(file_path)

    all_results = sort_dict(all_results)

    unit = "MiB" if RESULT == "Memory" else "% of core usage"
    data = {
        "Authorization version": [],
        "Verify version": [],
        f"CPU ({unit})": [],
        f"Memory ({unit})": [],
    }
    for auth_conc in all_results:
        # if auth_conc == "attack":
        #     continue
        for verify_conc in all_results[auth_conc]:
            # if verify_conc == "attack":
            #     continue
            for concurrency1 in all_results[auth_conc][verify_conc]:
                for concurrency2 in all_results[auth_conc][verify_conc][concurrency1]:
                    for r in all_results[auth_conc][verify_conc][concurrency1][concurrency2]:
                        cpu = 0
                        memory = 0
                        for service in r["top"]:
                            for container in r["top"][service]:
                                cpu += int(
                                    r["top"][service][container]["cpu"].split("m")[0]
                                )/10
                                memory += int(
                                    r["top"][service][container]["mem"].split("Mi")[0]
                                )
                        data["Authorization version"].append(
                            auth_conc
                            if auth_conc != "attack"
                            else f"c = {concurrency1}"
                        )
                        data["Verify version"].append(
                            verify_conc
                            if verify_conc != "attack"
                            else f"c = {concurrency2}"
                        )
                        data[f"CPU ({unit})"].append(cpu)
                        data[f"Memory ({unit})"].append(memory)

    # df = pd.DataFrame(data)
    # sns.set_theme(rc={"figure.figsize": SIZE})
    # ax = sns.scatterplot(data=data, x="Test", y="Relative frequency")
    ax = sns.pointplot(
        data=data,
        x="Authorization version",
        hue="Verify version",
        y=f"{RESULT} ({unit})",
        linestyle="none",
        palette=sns.color_palette("colorblind"),
    )

    # for i, row in df.iterrows():
    #     # Get the x position corresponding to the categorical tick.
    #     # ax.get_xticks() returns the positions of the ticks, which should align with the order of your categories.
    #     xtick_positions = ax.get_xticks()
    #     # Assuming the categories are in order
    #     x_pos = xtick_positions[i]
    #     y_pos = row["Relative frequency"]
    #     # Add an offset to y to avoid overlapping the marker
    #     ax.text(x=x_pos, y=y_pos + 0.02, s=f"{y_pos:.3f}", ha='center', va='bottom', fontdict={"size": 12*SIZE_RATION})

    if RESULT == "CPU":
        plt.legend(loc='lower left')

    plt.ylim(0)
    plt.title(f"{RESULT} used in each setup", fontdict={"size": 17 * SIZE_RATION})
    
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True)

    ax.yaxis.label.set_fontsize(15 * SIZE_RATION)
    ax.xaxis.label.set_fontsize(15 * SIZE_RATION)
    ax.tick_params(labelsize=12 * SIZE_RATION)
    plt.tight_layout()
    plt.savefig(f"resources_{RESULT}.pdf")

    plt.show()


if __name__ == "__main__":
    main()
