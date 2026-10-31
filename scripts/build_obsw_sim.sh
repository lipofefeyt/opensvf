#!/usr/bin/env bash
# Build bin/obsw_sim from the openobsw release pinned in .openobsw-version.
#
# The L3 suite (tests/system) and the HIL campaign run against this binary,
# both locally and in CI, so a result always names the openobsw it met.
#
# Usage:
#   bash scripts/build_obsw_sim.sh            # clone the pinned tag and build
#   OPENOBSW_SRC=/path/to/openobsw bash scripts/build_obsw_sim.sh
#                                             # build an existing checkout
#                                             # (warns if it is not the pin)
# Needs: git, cmake, ninja, a C compiler, python3 with venv.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
ref="$(tr -d '[:space:]' < "$repo/.openobsw-version")"
work="$repo/build/openobsw-$ref"
src="${OPENOBSW_SRC:-$work/src}"

if [ -z "${OPENOBSW_SRC:-}" ]; then
    if [ ! -d "$src/.git" ]; then
        rm -rf "$src"
        git clone --quiet --depth 1 --branch "$ref" \
            https://github.com/lipofefeyt/openobsw.git "$src"
    fi
else
    actual="$(git -C "$src" describe --tags --always 2>/dev/null || echo unknown)"
    [ "$actual" = "$ref" ] || echo "[build_obsw_sim] warning: $src is $actual, pin is $ref" >&2
fi

# Isolated venv for openobsw's SRDB code generator (obsw_srdb).
if [ ! -x "$work/venv/bin/python" ]; then
    python3 -m venv "$work/venv"
    "$work/venv/bin/pip" install --quiet --disable-pip-version-check "$src/srdb"
fi

PATH="$work/venv/bin:$PATH" cmake -S "$src" -B "$work/build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DOBSW_BUILD_TESTS=OFF -DOBSW_BUILD_SIM=ON >/dev/null
PATH="$work/venv/bin:$PATH" cmake --build "$work/build" --target obsw_sim >/dev/null

mkdir -p "$repo/bin"
cp "$work/build/sim/obsw_sim" "$repo/bin/obsw_sim"
echo "[build_obsw_sim] bin/obsw_sim built from openobsw $ref"
