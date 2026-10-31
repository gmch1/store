#!/system/bin/sh
set -eu
base=/data/adb/ming-store
unit=${1:-}
action=${2:-status}
case "$unit" in store|sshd|health|ddns) ;; *) echo 'Unit: store | sshd | health | ddns' >&2; exit 2;; esac
case "$action" in
    start|restart) /system/bin/sh "$base/guardian.sh" ;;
    stop|status) ;;
    *) echo 'Action: start | stop | restart | status' >&2; exit 2;;
esac
exec /system/bin/sh "$base/enter.sh" python /app/deploy/android/service_control.py "$unit" "$action"
