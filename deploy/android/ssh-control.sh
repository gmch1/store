#!/system/bin/sh
exec /system/bin/sh /data/adb/ming-store/services.sh sshd "${1:-status}"
