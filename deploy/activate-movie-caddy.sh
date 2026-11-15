#!/bin/sh
set -eu
cd /home/manfred/ai-local/services/movie-wall
if ! sudo -n grep -q 'http://movie.nuc.local' /etc/caddy/Caddyfile; then
    backup="/etc/caddy/Caddyfile.movie-wall-$(date +%Y%m%d%H%M%S).bak"
    sudo -n cp -p /etc/caddy/Caddyfile "$backup"
    sudo -n sh -c 'printf "\n" >> /etc/caddy/Caddyfile; cat /home/manfred/ai-local/services/movie-wall/deploy/movie-wall.caddy >> /etc/caddy/Caddyfile'
    if ! sudo -n caddy validate --config /etc/caddy/Caddyfile; then
        sudo -n cp -p "$backup" /etc/caddy/Caddyfile
        exit 1
    fi
    sudo -n systemctl reload caddy
fi
