import os
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
import json
import pandas as pd
from matplotlib.lines import Line2D  # Import Line2D for the line legend

COMPARISON = 5
SIZE = (7, 5)
SIZE_RATION = SIZE[1] / COMPARISON


RESULTS_DIR = "results/"

CONCURRENCY = "multiple"  # singular or multiple
AMOUNT = 100  # 10 or 100
MAX_ITERATIONS = 5000


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
    return results


def read_requests_trace(file_path):
    results = {}
    with open(file_path, "r") as f:
        content = f.read()
    for result in content.split(
        "\n-------------------------------------------------------\n"
    ):
        try:
            lines = result.split("\n")
            if not lines[0]:
                break
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


# Define the function
def f(x, second=1):
    return 1 / x * second


def main():
    # This list will hold the results from all files
    all_results = {}

    # Iterate over items in the current directory
    for item in os.listdir("results/"):
        info = item.split("_")
        amount = int(info[1].split("-")[1])
        s = info[2].split("-")
        auth_conc = f"c{s[1]}" if s[0] == "auth" else f"v{s[1]}"
        s = info[3].split("-")
        verify_conc = f"c{s[1]}" if s[0] == "verify" else f"v{s[1]}"

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
                pod_results.extend(read_results_pod(file_path))
            elif filename == "requests_trace.txt":
                for i in (r := read_requests_trace(file_path)):
                    all_results[amount][auth_conc][verify_conc][i] = {
                        "requests_trace": r[i]
                    }

        for p in pod_results:
            _id = p["headers"]["Ce-Id"]
            if _id not in all_results[amount][auth_conc][verify_conc]:
                continue
            #     all_results[amount][auth_conc][verify_conc][_id] = {}
            all_results[amount][auth_conc][verify_conc][_id]["pod_results"] = p

    all_results = sort_dict(all_results)
    experiment = "versions" if CONCURRENCY == "singular" else "concurrency"
    data = {
        f"Authorization {experiment}": [],
        f"Verify {experiment}": [],
        "Relative frequency": [],
    }
    for amount in all_results:
        if amount != AMOUNT:
            continue
        for auth in all_results[amount]:
            print(f"{auth} -> {all_results[amount][auth].keys()}")
            if CONCURRENCY == "singular" and auth.startswith("c"):
                continue
            if CONCURRENCY == "multiple" and auth.startswith("v"):
                continue
            for verify in all_results[amount][auth]:
                if CONCURRENCY == "singular" and verify.startswith("c"):
                    continue
                if CONCURRENCY == "multiple" and verify.startswith("v"):
                    continue
                x = 0
                l = 1
                print(f"Len {len(all_results[amount][auth][verify])}")
                for r in (c := all_results[amount][auth][verify]):
                    if "pod_results" in c[r]:
                        if (
                            c[r]["pod_results"]["body"].get("message")
                            == "Transaction successful"
                        ):
                            x += 1
                        l += 1
                data[f"Authorization {experiment}"].append(int(auth[1:]))
                data[f"Verify {experiment}"].append(int(verify[1:]))
                data["Relative frequency"].append(x / l)
                print(x)

    fig, ax = plt.subplots()
    sns.set_theme(rc={"figure.figsize": SIZE})
    ax = sns.scatterplot(
        data=data,
        x=f"Authorization {experiment}",
        hue=f"Verify {experiment}",
        y="Relative frequency",
        palette=sns.color_palette("colorblind"),
        ax=ax,
    )
    scatter_legend = ax.legend(
        title=f"Verify {experiment}", bbox_to_anchor=(0.62 if CONCURRENCY == 'singular' else 0.59 if AMOUNT == 10 else 0.41, 1), loc="upper right"
    )
    ax.add_artist(scatter_legend)
    # ax2 = ax.twinx()
    # for i, row in df.iterrows():
    #     # Get the x position corresponding to the categorical tick.
    #     # ax.get_xticks() returns the positions of the ticks, which should align with the order of your categories.
    #     xtick_positions = ax.get_xticks()
    #     # Assuming the categories are in order
    #     x_pos = xtick_positions[i]
    #     y_pos = row["Relative frequency"]
    #     # Add an offset to y to avoid overlapping the marker
    #     ax.text(x=x_pos, y=y_pos + 0.02, s=f"{y_pos:.3f}", ha='center', va='bottom', fontdict={"size": 12*SIZE_RATION})

    plt.ylim(0, 1)
    plt.title(
        f"Relative frequency of a successful attack with\nconcurrency {'=' if CONCURRENCY == 'singular' else r'$\geq$'} 1 and amount = {AMOUNT}\n",
        fontdict={"size": 17 * SIZE_RATION},
    )
    ax.yaxis.label.set_fontsize(15 * SIZE_RATION)
    ax.xaxis.label.set_fontsize(15 * SIZE_RATION)
    ax.tick_params(labelsize=12 * SIZE_RATION)

    x_values = np.linspace(1, 5 if CONCURRENCY == 'singular' else 3, 500)
    print(x_values)
    x_values = x_values[x_values != 0]  # Remove zero to avoid division error

    # Compute y values
    if AMOUNT == 10 or CONCURRENCY == "multiple":
        y_values = f(x_values) if CONCURRENCY == "singular" else x_values[1:] * 0
        df = pd.DataFrame(
            {
                "x": x_values if CONCURRENCY == "singular" else x_values[1:],
                "y": y_values,
            }
        )
        sns.lineplot(data=df, x="x", y="y", linestyle="dashed", ax=ax)
        plt.legend(
            [
                Line2D(
                    [0],
                    [0],
                    linestyle="dashed",
                    color=sns.color_palette()[0],
                    linewidth=2,
                )
            ],
            [r"$P = \frac{1}{v_a}$" if CONCURRENCY == 'singular' else r"$P = \left\{ \substack{ \frac{1}{v_a}\quad \text{if } c_a = 1 \\ 0\quad \text{otherwise} } \right.$" if AMOUNT == 10 else r"$P = \left\{ \substack{ \frac{1}{v_a}*\frac{1}{v_t}\quad \text{if } c_a = 1 \text{ and } c_t = 1 \\ 0\quad \text{otherwise} } \right.$"],
            title=r"Theoretical probability",
            bbox_to_anchor=(1, 1),
            loc="upper right",
            fontsize=12 * SIZE_RATION,
        )
    else:
        labels = []
        labels_lines = []
        for i in range(1, 6):
            y_values = f(x_values, second=1 / i)
            df = pd.DataFrame({"x": x_values, "y": y_values})
            sns.lineplot(data=df, x="x", y="y", linestyle="dashed", ax=ax)
            labels.append(r"$P = \frac{1}{v_a}*\frac{1}{" + str(i) + r"}$")
            labels_lines.append(
                Line2D(
                    [0],
                    [0],
                    linestyle="dashed",
                    color=sns.color_palette()[i - 1],
                    linewidth=2,
                )
            )
        plt.legend(
            labels_lines,
            labels,
            title=r"Theoretical probability"
            + "\n"
            + r"($P = \frac{1}{v_a}*\frac{1}{v_t}$)",
            bbox_to_anchor=(1, 1),
            loc="upper right",
            fontsize=12 * SIZE_RATION,
        )

    # Create a DataFrame for seaborn
    # plt.legend([Line2D([0], [0], linestyle='dashed', linewidth=2), Line2D([0], [0], linestyle='dashed', linewidth=2)], ["Theoretical values", "test"], bbox_to_anchor=(1, 1), loc="upper right")

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True)
    ax.set_xticks(list(range(1, 6)) if CONCURRENCY == "singular" else list(range(1, 4)))

    plt.tight_layout()
    plt.savefig(f"concurrency_c{CONCURRENCY}_a{AMOUNT}.pdf")

    plt.show()


if __name__ == "__main__":
    main()
