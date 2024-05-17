#!/usr/bin/env sh
# assemble.sh
# Copyright 2024 Andrés Botero 

set -euv

echo "assemble.sh"

ssh-agent
ssh-add

mkdir -p "build"

username="abotero"
host_win="pag-pc-mini.local"
host_mac="andress-mac-mini.local"

prefix_mac="${username}@${host_mac}"

echo "Pushing MacOS boostrap code"
script_filename="bootstrap_mac.sh"
scp "scripts/remote_build_mac.sh" "${prefix_mac}:${script_filename}"

echo "Executing MacOS code"
ssh "$prefix_mac" sh "$script_filename"

echo "Pulling MacOS artifact"
scp "${prefix_mac}:tmp/vertexforge_build/build/mac.zip" "build/mac.zip"


prefix_win="${username}@${host_win}"

echo "Pushing Windows boostrap code"
script_filename="bootstrap_win.ps1"
scp "scripts/remote_build_win.ps1" "${prefix_win}:${script_filename}"

echo "Executing Windows code"
ssh "$prefix_win" powershell "./${script_filename}"

echo "Pulling Windows artifact"
scp -X buffer=204800 "${prefix_win}:/tmp/vertexforge_build/build/win.zip" "build/win.zip"

# the buffer=204800 is to work around a bug in OpenSSH
