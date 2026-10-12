#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${QMLLINT:-}" ]]; then
  qmllint="$QMLLINT"
elif [[ -x /usr/lib/qt6/bin/qmllint ]]; then
  qmllint=/usr/lib/qt6/bin/qmllint
else
  qmllint=qmllint6
fi

if (($#)); then
  files=("$@")
else
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
  mapfile -d '' -t files < <(find . -type d \( -name .git -o -name .venv -o -path ./tests/fixtures \) -prune \
    -o -type f -name '*.qml' -print0)
fi
((${#files[@]})) || exit 0

help=$("$qmllint" --help)
flags=(--ignore-settings)
for category in 'import' 'unresolved-type type' 'unqualified' 'missing-property property' \
  'signal-handler-parameters signal' 'inheritance-cycle' 'uncreatable-type'; do
  for name in $category; do
    if grep -qE "^ +--${name} " <<< "$help"; then
      flags+=("--$name" disable)
      break
    fi
  done
done
if grep -qE '^ +.*--max-warnings ' <<< "$help"; then
  flags+=(-W 0)
fi
for file in "${files[@]}"; do
  "$qmllint" "${flags[@]}" "$file"
done
