#!/bin/sh
# 只增加 movie.nuc.local，不更改其他 DNS、分流或上游配置。
set -eu
config=/etc/adguardhome/adguardhome.yaml
if [ -f "$config" ]; then
    if ! grep -q 'domain: movie.nuc.local' "$config"; then
        grep -q '^  rewrites:' "$config"
        cp -p "$config" "$config.movie-wall-$(date +%Y%m%d%H%M%S).bak"
        /etc/init.d/adguardhome stop
        awk '/^  rewrites:/ { print; print "    - domain: movie.nuc.local\n      answer: 192.168.50.157\n      enabled: true"; next } { print }' "$config" > "$config.movie-wall.tmp"
        cat "$config.movie-wall.tmp" > "$config"
        /etc/init.d/adguardhome start
    fi
else
    if ! uci -q show dhcp | grep -q "name='movie.nuc.local'"; then
        cp -p /etc/config/dhcp "/etc/config/dhcp.movie-wall-$(date +%Y%m%d%H%M%S).bak"
        entry=$(uci add dhcp domain)
        uci set "dhcp.$entry.name=movie.nuc.local"
        uci set "dhcp.$entry.ip=192.168.50.157"
        uci commit dhcp
        /etc/init.d/dnsmasq reload
    fi
fi
