#!/system/bin/sh
# All dependencies are in device-encrypted storage; do not wait for user unlock.
exec /system/bin/sh /data/adb/ming-store/guardian.sh
