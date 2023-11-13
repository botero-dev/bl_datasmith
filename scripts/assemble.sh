#!/usr/bin/env sh

username="abotero"
host_win="pag-pc-mini.local"

prefix="${username}@${host_win}"

echo "Pushing boostrap code"
scp scripts/windows-remote-build.ps1 "${prefix}:bootstrap_vertexforge_windows.ps1"

echo "Executing code"
ssh "$prefix" powershell bootstrap_vertexforge_windows.ps1

echo "Pulling artifact"
scp "${prefix}:/tmp/vertexforge_build/build/win.zip build/win.zip"
