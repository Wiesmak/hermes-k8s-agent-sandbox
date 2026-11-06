#!/bin/sh
set -eu
# Read-only-rootfs arbitrary UID support: supply an NSS entry from writable /tmp.
if ! getent passwd "$(id -u)" >/dev/null 2>&1; then
    task_passwd=$(mktemp /tmp/hermes-passwd.XXXXXX)
    cat /etc/passwd > "$task_passwd"
    printf 'sandbox:x:%s:%s:Sandbox:/workspace:/bin/bash\n' "$(id -u)" "$(id -g)" >> "$task_passwd"
    export NSS_WRAPPER_PASSWD="$task_passwd"
    export NSS_WRAPPER_GROUP=/etc/group
    export LD_PRELOAD=/usr/lib64/libnss_wrapper.so
fi
exec /opt/runtime/venv/bin/uvicorn main:app --app-dir /opt/runtime --host 0.0.0.0 --port 8888 --no-access-log
