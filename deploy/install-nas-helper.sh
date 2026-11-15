#!/bin/sh
set -eu
cd /home/manfred/ai-local/services/movie-wall
test -x /usr/sbin/mount.cifs
test -x /usr/bin/smbclient
changed=0
if ! sudo -n cmp -s deploy/nas_helper.py /usr/local/libexec/movie-wall-nas-helper.py; then
    sudo -n install -D -m 755 deploy/nas_helper.py /usr/local/libexec/movie-wall-nas-helper.py
    changed=1
fi
sudo -n install -m 644 deploy/movie-wall-nas-helper.service /etc/systemd/system/movie-wall-nas-helper.service
sudo -n install -m 644 deploy/movie-wall.service /etc/systemd/system/movie-wall.service
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now movie-wall-nas-helper.service
if [ "$changed" -eq 1 ]; then
    sudo -n systemctl restart movie-wall-nas-helper.service
fi
sudo -n systemctl is-active movie-wall-nas-helper.service
