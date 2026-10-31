#!/system/bin/sh
set -eu
base=/data/adb/ming-store
case "${1:-status}" in
    exec)
        shift
        exec /system/bin/sh "$base/enter.sh" "$@"
        ;;
    *) exec /system/bin/sh "$base/services.sh" store "${1:-status}" ;;
esac
