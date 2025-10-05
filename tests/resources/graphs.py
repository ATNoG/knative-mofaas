import os
import seaborn as sns
import matplotlib.pyplot as plt
import pandas as pd

COMPARISON = 4.5
SIZE = (7, 5)
SIZE_RATION = SIZE[1] / COMPARISON


RESULTS_DIR = "results/"
RESULT = "CPU"  # Memory or CPU
REMOVE_IDLE = True
MAX_ITERATIONS = 1000

MARKERS = ["o", "s", "X", "P", "d", "^", ">", "<"]


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


def delete_idle(result, function: str, ver: str, conc: str):
    if ver != "attack":
        for i in range(len(result)):
            keys = list(result[i]["top"].keys())
            for k in keys:
                if function in k:
                    if k != f"{function}-{ver}":
                        if REMOVE_IDLE:
                            del result[i]["top"][k]
                        # else:   
                        #     del result[i]["top"][k]["envoy"]
    # for i in range(len(result)):
    #     keys = list(result[i]["top"].keys())
    #     for k in keys:
    #         if "envoy" in result[i]["top"][k]:
    #             del result[i]["top"][k]["envoy"]
    


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
                all_results[auth_conc][verify_conc][concurrency1][concurrency2] = (
                    read_top(file_path)
                )
                delete_idle(
                    result=all_results[auth_conc][verify_conc][concurrency1][
                        concurrency2
                    ],
                    function="authorization",
                    ver=auth_conc,
                    conc=concurrency1,
                )
                delete_idle(
                    result=all_results[auth_conc][verify_conc][concurrency1][
                        concurrency2
                    ],
                    function="verify-transaction",
                    ver=verify_conc,
                    conc=concurrency2,
                )
                # if concurrency1 == "0":
                #     print(all_results[auth_conc][verify_conc][concurrency1][concurrency2][0])
                # exit()

                # print(verify_conc)
                # print(concurrency1)
                # print(concurrency2)
                # exit()

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
                    for r in all_results[auth_conc][verify_conc][concurrency1][
                        concurrency2
                    ]:
                        cpu = 0
                        memory = 0
                        for service in r["top"]:
                            for container in r["top"][service]:
                                cpu += (
                                    int(
                                        r["top"][service][container]["cpu"].split("m")[
                                            0
                                        ]
                                    )
                                    / 10
                                )
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
        markers=MARKERS,
        scale=1.7,
    )

        # --- identify main lines (with markers) ---
    main_lines = [line for line in ax.lines if line.get_marker() != 'None']

    # get hue labels from legend
    _, hue_labels = ax.get_legend_handles_labels()

    # sanity check
    print(f"Detected {len(main_lines)} main lines for {len(hue_labels)} hues")

    # --- extract data for each hue ---
    grouped = {}
    for label, line in zip(hue_labels, main_lines):
        xy = line.get_xydata()
        grouped[label] = pd.DataFrame(xy, columns=["x", "y"])

    # --- display results ---
    for hue, df in grouped.items():
        print(f"\nHue: {hue}")
        print(df.to_string(index=False))

    # for i, row in df.iterrows():
    #     # Get the x position corresponding to the categorical tick.
    #     # ax.get_xticks() returns the positions of the ticks, which should align with the order of your categories.
    #     xtick_positions = ax.get_xticks()
    #     # Assuming the categories are in order
    #     x_pos = xtick_positions[i]
    #     y_pos = row["Relative frequency"]
    #     # Add an offset to y to avoid overlapping the marker
    #     ax.text(x=x_pos, y=y_pos + 0.02, s=f"{y_pos:.3f}", ha='center', va='bottom', fontdict={"size": 12*SIZE_RATION})

    # if RESULT == "CPU":
    #     plt.legend()

    if RESULT == "CPU":
        plt.ylim(0, 50)
    else:
        plt.ylim(0, 1210)
    plt.xlim(-0.2, 7.5)
    plt.title(
        f"{RESULT} used in each setup{'\nwithout idle variants' if REMOVE_IDLE else ''}",
        fontdict={"size": 17 * SIZE_RATION},
    )
    ax.legend(
        title="Verify version",
        loc="lower left",               #  if RESULT != "CPU" or REMOVE_IDLE else "upper right"
        fontsize=13 * SIZE_RATION,
        title_fontsize=13 * SIZE_RATION,
        ncol=2,
        bbox_to_anchor=(-0.02, -0.02),          #  if RESULT != "CPU" or REMOVE_IDLE else (1.05, 1.05)
    )

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True)

    ax.yaxis.label.set_fontsize(15 * SIZE_RATION)
    ax.xaxis.label.set_fontsize(15 * SIZE_RATION)
    ax.tick_params(labelsize=12 * SIZE_RATION)
    plt.tight_layout()
    plt.savefig(
        f"resources_{RESULT}.pdf" if not REMOVE_IDLE else f"resources_{RESULT}_idle.pdf"
    )

    plt.show()


if __name__ == "__main__":
    main()
