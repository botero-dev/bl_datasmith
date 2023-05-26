#!/usr/bin/env python3
# get_path_for_ue.py
# Copyright Andrés Botero 2023

import argparse
import json


parser = argparse.ArgumentParser(description="Find an object in a JSON file by AppID")
parser.add_argument("file_path", help="Path to the JSON file")
parser.add_argument("app_id", help="ID of the object to find")
args = parser.parse_args()

with open(args.file_path, "r") as file:
    data = json.load(file)

apps = data["InstallationList"]
for obj in apps:
    if obj.get("AppName") == args.app_id:
        print(obj["InstallLocation"])
        break
