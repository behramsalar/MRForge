#!/usr/bin/env bash
# Installs ICA-AROMA (reference implementation, https://github.com/maartenmennes/ICA-AROMA)
# into tools/ICA-AROMA of this project, and the one small package it needs ("future") into
# the active Python environment. The pinned versions in its requirements.txt are NOT
# installed: they are from 2018 and do not exist for current Python; the script runs with
# current numpy, scipy, pandas, matplotlib and seaborn (checked on this project's data).
set -euo pipefail
cd "$(dirname "$0")/.."
# Pinned: the last commit of the maartenmennes repository tested with this project (2024-02-22, 21
# commits after tag v0.4.4-beta; it adds the -noplots option and changes the edge mask file).
TAG="${AROMA_COMMIT:-302f30db73759725002f1dcc07e8e0194de6c561}"
if [ ! -d tools/ICA-AROMA ]; then
  mkdir -p tools
  git clone --quiet https://github.com/maartenmennes/ICA-AROMA.git tools/ICA-AROMA
fi
git -C tools/ICA-AROMA checkout --quiet "$TAG"
python -m pip install --quiet future
echo "ICA-AROMA $(git -C tools/ICA-AROMA describe --tags --always) is in tools/ICA-AROMA"
