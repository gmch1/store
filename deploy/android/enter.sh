#!/system/bin/sh
# Run only as root. Mounts live in a private namespace and disappear on exit.
set -eu
base=/data/adb/ming-store
busybox=/data/adb/magisk/busybox
if [ "${STORE_PRIVATE_MOUNTS:-}" != 1 ]; then
    export STORE_PRIVATE_MOUNTS=1
    exec "$busybox" unshare -m --propagation private /system/bin/sh "$base/enter.sh" "$@"
fi
root="$base/rootfs"
mkdir -p "$root/dev" "$root/proc" "$root/sys"
mkdir -p "$root/maintenance-ssh" /data/adb/ming-sshd
chmod 700 /data/adb/ming-sshd "$root/maintenance-ssh"
"$busybox" mount --bind /dev "$root/dev"
"$busybox" mount --bind /dev/pts "$root/dev/pts"
"$busybox" mount -t proc proc "$root/proc"
"$busybox" mount --bind /sys "$root/sys"
"$busybox" mount -o remount,bind,ro "$root/sys"
"$busybox" mount --bind /data/adb/ming-sshd "$root/maintenance-ssh"
"$busybox" mount -o remount,bind,ro "$root/maintenance-ssh"
exec /system/bin/chroot "$root" /usr/bin/env -i \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/root LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 "$@"
