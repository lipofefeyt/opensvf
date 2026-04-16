#!/usr/bin/env bash
# download_fmu.sh — download pre-built FMU binaries from opensvf-kde releases
#
# Usage: bash scripts/download_fmu.sh [version]
# Default version: latest

set -euo pipefail

REPO="lipofefeyt/opensvf-kde"
FMU_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/models/fmu"
VERSION="${1:-latest}"

mkdir -p "$FMU_DIR"

echo "[fmu] Checking for FMU binaries in $FMU_DIR..."

FMUS=(
    "SpacecraftDynamics.fmu"
    "EpsFmu.fmu"
    "BatteryFmu.fmu"
    "SolarArrayFmu.fmu"
    "PcduFmu.fmu"
)

# Check if all FMUs already exist
ALL_PRESENT=true
for fmu in "${FMUS[@]}"; do
    if [ ! -f "$FMU_DIR/$fmu" ]; then
        ALL_PRESENT=false
        break
    fi
done

if [ "$ALL_PRESENT" = true ]; then
    echo "[fmu] All FMU binaries present — skipping download"
    exit 0
fi

# Try to download from GitHub releases
if command -v gh &>/dev/null; then
    echo "[fmu] Downloading FMU binaries from $REPO releases..."
    if [ "$VERSION" = "latest" ]; then
        RELEASE=$(gh api repos/$REPO/releases/latest --jq '.tag_name' 2>/dev/null || echo "")
    else
        RELEASE="$VERSION"
    fi

    if [ -n "$RELEASE" ]; then
        for fmu in "${FMUS[@]}"; do
            if [ ! -f "$FMU_DIR/$fmu" ]; then
                echo "[fmu] Downloading $fmu ($RELEASE)..."
                gh release download "$RELEASE" \
                    --repo "$REPO" \
                    --pattern "$fmu" \
                    --dir "$FMU_DIR" 2>/dev/null || \
                    echo "[fmu] WARNING: $fmu not found in release $RELEASE"
            fi
        done
        echo "[fmu] Done"
        exit 0
    fi
fi

# Fallback: FMUs already committed to repo
echo "[fmu] GitHub release not available — using committed FMU binaries"
echo "[fmu] FMUs present:"
for fmu in "${FMUS[@]}"; do
    if [ -f "$FMU_DIR/$fmu" ]; then
        echo "  ✓ $fmu"
    else
        echo "  ✗ $fmu (MISSING)"
    fi
done
