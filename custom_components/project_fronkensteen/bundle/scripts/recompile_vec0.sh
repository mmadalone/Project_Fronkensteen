#!/bin/bash
# =============================================================================
# Recompile sqlite-vec (vec0.so) for HA Core container
# =============================================================================
# Called by the sqlite_vec_recompile blueprint after HA Core updates.
# Must run inside the HA Core container (Alpine/musl, aarch64).
# =============================================================================
set -e

WORKDIR="/tmp/sqlite-vec-build"
OUTPATH="/config/vec0.so"

echo "=== sqlite-vec recompile starting ==="

# Install build dependencies
apk add --no-cache build-base sqlite-dev git gettext >/dev/null 2>&1

# Clean previous build
rm -rf "$WORKDIR"
mkdir -p "$WORKDIR"
cd "$WORKDIR"

# Clone source
git clone --depth 1 https://github.com/asg017/sqlite-vec.git .
echo "Cloned sqlite-vec $(cat VERSION)"

# Remove musl-incompatible typedefs (lines 68-70 in current source)
sed -i '/^typedef u_int8_t uint8_t;$/d' sqlite-vec.c
sed -i '/^typedef u_int16_t uint16_t;$/d' sqlite-vec.c
sed -i '/^typedef u_int64_t uint64_t;$/d' sqlite-vec.c

# Generate header manually (envsubst may fail on minimal Alpine)
VERSION=$(cat VERSION)
VERSION_MAJOR=$(echo "$VERSION" | cut -d. -f1)
VERSION_MINOR=$(echo "$VERSION" | cut -d. -f2)
VERSION_PATCH=$(echo "$VERSION" | cut -d. -f3 | cut -d- -f1)
SOURCE=$(git rev-parse HEAD)
DATE=$(date +'%FT%TZ%z')

cat > sqlite-vec.h << HEADER
#ifndef SQLITE_VEC_H
#define SQLITE_VEC_H
#ifndef SQLITE_CORE
#include "sqlite3ext.h"
#else
#include "sqlite3.h"
#endif
#ifdef SQLITE_VEC_STATIC
  #define SQLITE_VEC_API
#else
  #ifdef _WIN32
    #define SQLITE_VEC_API __declspec(dllexport)
  #else
    #define SQLITE_VEC_API
  #endif
#endif
#define SQLITE_VEC_VERSION "v${VERSION}"
#define SQLITE_VEC_DATE "${DATE}"
#define SQLITE_VEC_SOURCE "${SOURCE}"
#define SQLITE_VEC_VERSION_MAJOR ${VERSION_MAJOR}
#define SQLITE_VEC_VERSION_MINOR ${VERSION_MINOR}
#define SQLITE_VEC_VERSION_PATCH ${VERSION_PATCH}
#ifdef __cplusplus
extern "C" {
#endif
SQLITE_VEC_API int sqlite3_vec_init(sqlite3 *db, char **pzErrMsg,
                  const sqlite3_api_routines *pApi);
#ifdef __cplusplus
}
#endif
#endif
HEADER

# Compile
mkdir -p dist
cc -fPIC -shared -Ivendor/ -O3 -lm sqlite-vec.c -o dist/vec0.so 2>&1 | grep -i error || true
echo "Compiled vec0.so: $(ls -la dist/vec0.so)"

# Copy to /config/
cp dist/vec0.so "$OUTPATH"

# Validate
python3 -c "
import sqlite3
c = sqlite3.connect(':memory:')
c.enable_load_extension(True)
c.load_extension('/config/vec0')
c.execute(\"CREATE VIRTUAL TABLE _t USING vec0(e float[4])\")
c.execute(\"INSERT INTO _t(rowid, e) VALUES (1, '[1,0,0,0]')\")
r = c.execute(\"SELECT rowid FROM _t WHERE e MATCH '[1,0,0,0]' AND k=1\").fetchall()
assert len(r) > 0, 'KNN test failed'
print('OK — vec0.so validated')
c.close()
"

# Cleanup
rm -rf "$WORKDIR"
apk del --no-cache build-base sqlite-dev git gettext >/dev/null 2>&1 || true

echo "=== sqlite-vec recompile complete ==="
