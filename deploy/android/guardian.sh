#!/system/bin/sh
# Magisk late_start entry. runit owns independent SSH, store and health services.
set -eu
base=/data/adb/ming-store
[ "$(id -u)" = 0 ] || exit 1
[ -x "$base/rootfs/usr/bin/runsvdir" ] || exit 1
echo -1000 > /proc/self/oom_score_adj
if [ -f "$base/guardian.log" ] && [ "$(stat -c %s "$base/guardian.log")" -gt 1048576 ]; then
    mv -f "$base/guardian.log" "$base/guardian.log.1"
fi
# flock closes its descriptor in the child; a second invocation is harmless.
/data/adb/magisk/busybox nohup /system/bin/sh "$base/enter.sh" \
    flock -n -o /run/services-guardian.lock runsvdir -P /services \
    >> "$base/guardian.log" 2>&1 < /dev/null &
