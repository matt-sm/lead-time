from dateutil import parser
from datetime import datetime, timedelta, timezone
import requests
import json
import matplotlib.pyplot as plt
import os
import boto3
from botocore.exceptions import ClientError

plt.rcdefaults()
s3_client = boto3.client("s3")

MAPPINGS = {}


def get_builds(url):
    payload = ""
    headers = {"Authorization": f"Bearer {os.environ['BUILDKITE_TOKEN']}"}

    print(url)
    response = requests.request("GET", url, data=payload, headers=headers)

    if response.status_code != 200:
        return []

    builds = [
        parser.parse(c["created_at"]) for c in response.json() if not c["blocked"]
    ]

    if "next" in response.links.keys():
        next_url = response.links["next"]["url"]
        builds.extend(get_builds(next_url))

    return builds


def get_commits(url, querystring):
    payload = ""
    headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}

    print(url)
    response = requests.request(
        "GET", url, data=payload, headers=headers, params=querystring
    )

    if response.status_code != 200:
        return []

    commits = [parser.parse(c["commit"]["committer"]["date"]) for c in response.json()]

    if "next" in response.links.keys():
        next_url = response.links["next"]["url"]
        commits.extend(get_commits(next_url, ""))

    return commits


def get_builds_for_period(period):
    builds = {}
    for key in MAPPINGS.keys():
        build_name = key
        url = f"https://api.buildkite.com/v2/organizations/myob/pipelines/{build_name}/builds?branch=master&state=passed&created_from={period}"
        builds[key] = get_builds(url)

    return builds


def get_commits_for_period(period):
    commits = {}
    for key in MAPPINGS.keys():
        repo_name = MAPPINGS[key]

        url = f"https://api.github.com/repos/myob-technology/{repo_name}/commits"
        querystring = {"since": period}
        commits[key] = get_commits(url, querystring)

    return commits


def calc_lead_times(deploys, commits):
    lead_times = {}
    for key in commits.keys():
        lead_times[key] = []

        if len(commits[key]) == 0:
            lead_times[key] = 0
            continue

        for commit in commits[key]:
            # find the deploy that matches the commit
            deploy = next(
                (d for d in reversed(deploys[key]) if commit < d),
                datetime.now(timezone.utc),
            )
            lead_time = deploy - commit
            lead_times[key].append(lead_time)

        # calc the avg and convert to days
        if len(lead_times[key]) > 0:
            avg = sum(lead_times[key], timedelta()) / len(lead_times[key])
            lead_times[key] = avg.total_seconds() / 86400
        else:
            lead_times[key] = 0

    return lead_times


def plot_items(plots):
    for plot in plots:
        filename = plot[2]
        plt.figure()
        plt.barh(*zip(*plot[0].items()))
        plt.title(plot[1])
        plt.tight_layout()
        plt.savefig(filename)
        with open(filename, "rb") as f:
            try:
                s3_client.upload_file(filename, os.environ["BUCKET_NAME"], filename)
            except ClientError as e:
                print(e)


def key_to_value_lengths(items):
    return {key: len(value) for key, value in items.items()}


def main():
    period = datetime.today() - timedelta(days=30)
    period_str = period.strftime("%Y-%m-%dT%H:%M:%SZ")

    commits = get_commits_for_period(period_str)
    builds = get_builds_for_period(period_str)

    lead_times = calc_lead_times(builds, commits)
    plot_items(
        [
            (key_to_value_lengths(builds), "Deploy Frequency", "freq.png"),
            (key_to_value_lengths(commits), "Commit Frequency", "commit.png"),
            (lead_times, "Average Lead Time (days)", "lead.png"),
        ]
    )


if __name__ == "__main__":
    main()
