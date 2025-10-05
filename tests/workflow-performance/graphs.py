import os
import seaborn as sns
import matplotlib.pyplot as plt
import json
import pandas as pd
import numpy as np
import sys
from pathlib import Path
from matplotlib.lines import Line2D

COMPARISON = 4.5
SIZE = (7, 5)
SIZE_RATION = SIZE[1] / COMPARISON


RESULTS_DIR = "results/"
RESULT = "vpf"  # vpf or ps
COMPARE = False
MAX_ITERATIONS = 1000

MARKERS = ["o", "s", "X", "P", "d", "|", ">"]


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
        print(f"{item} {RESULT}")
        if RESULT == "ps" and item =="test_versfunc-5_pathsize-5_concurrency-1_dt-attack_20251007213153":
            continue
        if RESULT == "vpf" and item == "test_versfunc-5_pathsize-5_concurrency-1_dt-attack_20250306105551":
            continue
        info = item.split("_")
        versfunc = int(info[1].split("-")[1])
        pathsize = int(info[2].split("-")[1])
        concurrency = int(info[3].split("-")[1])
        dt = info[4].split("-")[1]
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

    if RESULT == "vpf":
        data = {
            "Versions per function": [],
            "Execution time (s)": [],
            "Path size": [],
            "Concurrency": [],
            "Version": [],  # New column to distinguish versions
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
                            if "requests_trace" in c[r]:
                                if "pod_results" in c[r]:
                                    data["Execution time (s)"].append(
                                        c[r]["pod_results"]["time"] - c[r]["requests_trace"]["start"]
                                    )
                                    data["Versions per function"].append(versfunc)
                                    data["Concurrency"].append(concurrency)
                                    data["Path size"].append(pathsize)
                                    data["Version"].append("New")  # Mark as new version

        new_data = pd.DataFrame(data)

        if COMPARE:
            # Load old data
            old_data = pd.read_pickle("previous.pkl")
            # Filter new data for concurrency == 1
            new_data = new_data[new_data["Concurrency"] == 1]
            # Add "Version" column
            old_data["Version"] = "Old"
            old_data = old_data[old_data["Versions per function"] != "baseline"]

            f, (ax_top, ax_bottom) = plt.subplots(ncols=1, nrows=2, sharex=True, gridspec_kw={'hspace':0.1, 'height_ratios': [3, 3]}, figsize=SIZE)

            graph_top = sns.pointplot(
                data=old_data,
                x="Versions per function",
                y="Execution time (s)",
                linestyle="none",
                color=sns.color_palette("colorblind")[1],
                marker=MARKERS[1],
                scale=1.7,
                errorbar=("se", 2),
                capsize=.05,
                ax=ax_top
            )

            graph_bottom = sns.pointplot(
                data=new_data,
                x="Versions per function",
                y="Execution time (s)",
                linestyle="none",
                color=sns.color_palette("colorblind")[0],
                marker=MARKERS[0],
                scale=1.7,
                errorbar=("se", 2),
                capsize=.05,
                ax=ax_bottom
            )            

            graph_top_lims = (0.38, 0.4401) 
            graph_bottom_lims = (0.13, 0.1901) 
            ax_top.set_ylim(*graph_top_lims)
            ax_bottom.set_ylim(*graph_bottom_lims)
            graph_bottom.set_yticks(list(np.arange(*graph_bottom_lims, 0.01)))
            graph_top.set_yticks(list(np.arange(*graph_top_lims, 0.01)))

            sns.despine(ax=ax_bottom)
            sns.despine(ax=ax_top, bottom=True)
            d = .007  # how big to make the diagonal lines in axes coordinates
            # arguments to pass to plot, just so we don't keep repeating them
            kwargs = dict(transform=ax_top.transAxes, color='k', clip_on=False)
            ax_top.plot((-d, +d), (-d, +d), **kwargs)        # top-left diagonal

            kwargs.update(transform=ax_bottom.transAxes)  # switch to the bottom axes
            ax_bottom.plot((-d, +d), (1 - d, 1 + d), **kwargs)  # bottom-left diagonal

            graph_top.set(xlabel="", ylabel="Execution time (s)")
            graph_bottom.set(xlabel="Number of versions per function", ylabel="")
            graph_top.yaxis.label.set_position((-1, 0))

            graph_top.set_title(
                f"Execution time varying the number of\nversions per function",
                fontdict={"size": 17 * SIZE_RATION},
            )

            labels = ["Old", "New"]
            labels_markers = []
            for i in range(len(labels) - 1, -1, -1):
                labels_markers.append(
                    Line2D(
                        [0],
                        [0],
                        linestyle="",
                        marker=MARKERS[i],
                        color=sns.color_palette("colorblind")[i],
                        linewidth=2,
                        markersize=1.7*6
                    )
                )
            plt.legend(
                labels_markers,
                labels,
                title="Versions",
                fontsize=13 * SIZE_RATION,
                title_fontsize=13 * SIZE_RATION
            )
        else:
            # Only use new data
            combined_data = new_data

            ax = sns.pointplot(
                data=combined_data,
                x="Versions per function",
                y="Execution time (s)",
                hue="Concurrency",
                linestyle="none",
                palette=sns.color_palette("colorblind"),
                markers=MARKERS,
                scale=1.7,
                errorbar=("se", 2),
                capsize=.05
            )

            plt.title(
                f"Execution time varying the number of\nversions per function and concurrency",
                fontdict={"size": 17 * SIZE_RATION},
            )
            ax.legend(
                title="Concurrency",
                fontsize=13 * SIZE_RATION,
                title_fontsize=13 * SIZE_RATION,
            )
    else:
        data = {
            "Protection": [],
            "Execution time (s)": [],
            "Path size": [],
        }
        for versfunc in all_results:
            if versfunc != 5 and versfunc != 1:
                continue
            for pathsize in all_results[versfunc]:
                for concurrency in all_results[versfunc][pathsize]:
                    if concurrency != 5 and concurrency != 1 and concurrency != 2:
                        continue
                    print(concurrency)
                    for dt in all_results[versfunc][pathsize][concurrency]:
                        if dt == "attack" and versfunc == 1:
                            continue
                        # if dt == "attack" and concurrency == 1:
                        #     continue
                        for r in (
                            c := all_results[versfunc][pathsize][concurrency][dt]
                        ):
                            if "requests_trace" in c[r]:
                                if "pod_results" in c[r]:
                                    data["Execution time (s)"].append(
                                        c[r]["pod_results"]["time"]
                                        - c[r]["requests_trace"]["start"]
                                    )
                                    # if 'requests_trace' in (r := all_results[versfunc][pathsize][concurrency][dt]):
                                    # data["Execution time (s)"][-1].append(c[r]['pod_results']["time"] - c[r]['requests_trace']['start'])
                                    # data["Execution time (s)"].append(c[r]['requests_trace']['stop'] - c[r]['requests_trace']['start'])
                                    # data["Test"].append(f"Versions per function {versfunc}\nDeployment type {dt}\nConcurrency {concurrency}")
                                    data["Protection"].append(
                                        f"With MoFaaS and c = {concurrency}"
                                        if dt == "attack"
                                        else "Without MoFaaS"
                                    )
                                    data["Path size"].append(pathsize)
        ax = sns.pointplot(
            data=data,
            x="Path size",
            y="Execution time (s)",
            hue="Protection",
            linestyle="none",
            palette=sns.color_palette("colorblind"),
            markers=MARKERS,
            scale=1.7,
        )
        plt.title(
            f"Execution time varying the\npath size and concurrency",
            fontdict={"size": 17 * SIZE_RATION},
        )
        ax.legend(
            title="Protection",
            fontsize=13 * SIZE_RATION,
            title_fontsize=13 * SIZE_RATION,
        )

    # print(ax.get_lines()[0].get_data())
    # for i in ax.get_lines():
    #     print(i.get_data())

    if COMPARE and RESULT == "vpf":
        graph_top.spines["top"].set_visible(False)
        graph_top.spines["right"].set_visible(False)
        graph_top.grid(True)
        graph_bottom.grid(True)

        graph_top.yaxis.label.set_fontsize(15 * SIZE_RATION)
        graph_top.tick_params(labelsize=12 * SIZE_RATION)
        graph_bottom.yaxis.label.set_fontsize(15 * SIZE_RATION)
        graph_bottom.xaxis.label.set_fontsize(15 * SIZE_RATION)
        graph_bottom.tick_params(labelsize=12 * SIZE_RATION)
    else:
        plt.ylim(0, 0.4)
        plt.xlim(-0.3, 4.3)
        ax.get_legend()._loc = 2
        ax.get_legend().set_bbox_to_anchor((-0.015, 1.05))
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(True)

        ax.yaxis.label.set_fontsize(15 * SIZE_RATION)
        ax.xaxis.label.set_fontsize(15 * SIZE_RATION)
        ax.tick_params(labelsize=12 * SIZE_RATION)
    plt.tight_layout()
    plt.savefig(f"{RESULT}.pdf" if not COMPARE or RESULT != "vpf" else f"{RESULT}_compare.pdf")

    plt.show()


if __name__ == "__main__":
    main()
