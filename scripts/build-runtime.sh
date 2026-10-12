#!/usr/bin/env bash
# Builds llama.cpp (MIT), the embedding runtime: the pinned tag plus scripts/llama.cpp-no-logits.patch, static, with the
# Vulkan backend and multimodal support. Installs only llama-server, at $OMAFIND_DATA_DIR/runtime/bin/llama-server.
# Does nothing when that build is already there. Linux port of DigUp scripts/build-llama.sh (MIT, 6faa29e).
set -euo pipefail

# Run inside a memory-capped scope with no swap, so a runaway compile is killed there instead of throttling the
# whole session into zram swap. OMAFIND_BUILD_MEMORY_MAX=0 skips the scope.
MEMORY_MAX="${OMAFIND_BUILD_MEMORY_MAX:-12G}"
if [[ -z "${OMAFIND_BUILD_SCOPED:-}" && "$MEMORY_MAX" != 0 ]] && command -v systemd-run > /dev/null \
  && systemctl --user show-environment > /dev/null 2>&1; then
  exec systemd-run --user --scope --quiet --collect -p "MemoryMax=$MEMORY_MAX" -p MemorySwapMax=0 -- \
    env OMAFIND_BUILD_SCOPED=1 nice -n 19 ionice -c 3 "$0" "$@"
fi

TAG="${TAG:-b11461}"
SPIRV_HEADERS_TAG="${SPIRV_HEADERS_TAG:-vulkan-sdk-1.4.357.0}"
DATA="${OMAFIND_DATA_DIR:-$HOME/.local/share/omafind}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH="$HERE/llama.cpp-no-logits.patch"
CACHE="$DATA/cache"
SOURCE="$CACHE/src"
BUILD="$CACHE/build"
OUT="$DATA/runtime"
BIN="$OUT/bin/llama-server"

FLAGS=(
  -DCMAKE_BUILD_TYPE=Release
  -DBUILD_SHARED_LIBS=OFF
  -DGGML_VULKAN=ON
  -DGGML_CUDA=OFF
  -DGGML_BLAS=OFF
  -DGGML_RPC=OFF
  -DLLAMA_BUILD_SERVER=ON
  -DLLAMA_BUILD_MTMD=ON
  -DLLAMA_BUILD_TOOLS=ON
  -DLLAMA_BUILD_COMMON=ON
  -DLLAMA_BUILD_TESTS=OFF
  -DLLAMA_BUILD_EXAMPLES=OFF
  -DLLAMA_BUILD_APP=OFF
  -DLLAMA_BUILD_UI=OFF
  -DLLAMA_USE_PREBUILT_UI=OFF
  -DLLAMA_OPENSSL=OFF
  -DLLAMA_TOOLS_INSTALL=OFF
)
STAMP="$TAG $(sha256sum "$PATCH" | cut -c1-12) ${FLAGS[*]}"

mkdir -p "$DATA"
chmod 700 "$DATA"

if [[ -x "$BIN" && "$(cat "$OUT/BUILD" 2>/dev/null)" == "$STAMP" ]]; then
  exit 0
fi

if [[ ! -d "$SOURCE/.git" ]]; then
  mkdir -p "$CACHE"
  git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$TAG" https://github.com/ggml-org/llama.cpp "$SOURCE"
elif [[ "$(git -C "$SOURCE" describe --tags --exact-match 2>/dev/null)" != "$TAG" ]]; then
  git -C "$SOURCE" fetch --quiet --depth 1 origin tag "$TAG"
  git -C "$SOURCE" -c advice.detachedHead=false checkout --quiet --force "$TAG"
fi
# Without the patch, every input token costs n_vocab floats of logits (1 MiB with a 262k vocabulary) that a
# non-causal embedding model never reads. Reset first so a re-run never stacks the patch.
git -C "$SOURCE" checkout --quiet --force -- .
git -C "$SOURCE" apply "$PATCH"

# The shader step below drives ninja directly, so the build always uses the Ninja generator.
if ! command -v cmake > /dev/null || ! command -v ninja > /dev/null; then
  echo "cmake or ninja not found. Preferred fix: sudo pacman -S cmake ninja" >&2
  echo "Falling back to a private build venv with uv." >&2
  if [[ ! -x "$CACHE/cmake-venv/bin/cmake" ]]; then
    uv venv --quiet "$CACHE/cmake-venv"
    uv pip install --quiet --python "$CACHE/cmake-venv/bin/python" cmake ninja
  fi
  export PATH="$CACHE/cmake-venv/bin:$PATH"
fi

# The Vulkan backend needs the SPIRV-Headers CMake package. It is header-only, so a private install is cheap.
EXTRA=()
have_spirv_headers() {
  local dir
  for dir in /usr/lib /usr/lib64 /usr/share; do
    [[ -f "$dir/cmake/SPIRV-Headers/SPIRV-HeadersConfig.cmake" ]] && return 0
  done
  return 1
}
if ! have_spirv_headers; then
  echo "SPIRV-Headers not found. Preferred fix: sudo pacman -S spirv-headers" >&2
  echo "Falling back to a private install from $SPIRV_HEADERS_TAG." >&2
  if [[ ! -d "$CACHE/spirv-headers/share/cmake" ]]; then
    rm -rf "$CACHE/spirv-headers-src"
    git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$SPIRV_HEADERS_TAG" \
      https://github.com/KhronosGroup/SPIRV-Headers "$CACHE/spirv-headers-src"
    cmake -S "$CACHE/spirv-headers-src" -B "$CACHE/spirv-headers-build" -DCMAKE_INSTALL_PREFIX="$CACHE/spirv-headers" \
      -DSPIRV_HEADERS_ENABLE_TESTS=OFF -DSPIRV_HEADERS_ENABLE_INSTALL=ON > /dev/null
    cmake --install "$CACHE/spirv-headers-build" > /dev/null
  fi
  # ggml-vulkan finds the package but never links its target, so the include dir is passed by hand.
  EXTRA+=("-DCMAKE_PREFIX_PATH=$CACHE/spirv-headers"
    "-DCMAKE_CXX_STANDARD_INCLUDE_DIRECTORIES=$CACHE/spirv-headers/include")
fi

# Without a full clone the build number and commit cannot be derived, so `--version` would not name the tag.
COMMIT="$(git -C "$SOURCE" rev-parse --short HEAD)"
cmake -S "$SOURCE" -B "$BUILD" -G Ninja "${FLAGS[@]}" "${EXTRA[@]}" \
  "-DLLAMA_BUILD_NUMBER=${TAG#b}" "-DLLAMA_BUILD_COMMIT=$COMMIT" > /dev/null
# Each vulkan-shaders-gen process runs min(16, CPUs) glslc at once, and ninja would start one generator per job
# (about 144 glslc on 12 CPUs), so the shaders are generated first, one generator at a time, on a few CPUs.
SHADER_CPUS="${OMAFIND_SHADER_CPUS:-4}"
(( SHADER_CPUS >= 1 )) || SHADER_CPUS=1
TARGETS="$(ninja -C "$BUILD" -t targets all)"
mapfile -t SHADERS < <(sed -n 's|^\(ggml/src/ggml-vulkan/[^:/]*\.comp\.cpp\):.*|\1|p' <<< "$TARGETS")
if (( ${#SHADERS[@]} == 0 )); then
  echo "No Vulkan shader targets found in $BUILD" >&2
  exit 1
fi
cmake --build "$BUILD" --target vulkan-shaders-gen
taskset -c "0-$((SHADER_CPUS - 1))" ninja -C "$BUILD" -j 1 ggml/src/ggml-vulkan/ggml-vulkan-shaders.hpp "${SHADERS[@]}"

# Large translation units such as ggml-vulkan.cpp need about 2 GiB each.
AVAIL_GIB=$(awk '/^MemAvailable:/ { print int($2 / 1048576) }' /proc/meminfo)
LIMIT="$(cat "/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup)/memory.max" 2>/dev/null || echo max)"
if [[ "$LIMIT" =~ ^[0-9]+$ ]] && (( LIMIT / 1073741824 < AVAIL_GIB )); then
  AVAIL_GIB=$(( LIMIT / 1073741824 ))
fi
JOBS="${OMAFIND_BUILD_JOBS:-$(( AVAIL_GIB / 2 < $(nproc) ? AVAIL_GIB / 2 : $(nproc) ))}"
(( JOBS >= 1 )) || JOBS=1
cmake --build "$BUILD" --config Release -j "$JOBS" --target llama-server

install -D -m 0755 "$BUILD/bin/llama-server" "$BIN"
echo "$STAMP" > "$OUT/BUILD"
echo "Built llama.cpp $TAG (patched) into $OUT"
