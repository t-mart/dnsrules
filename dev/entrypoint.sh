#!/bin/sh
# unbound reads an address, never a name. `dnstap-ip` takes no hostname, and a
# resolver cannot use DNS to find the thing that configures it. So the dnsrules
# address is substituted here, once, before unbound starts.
#
# The default is the docker bridge gateway, which is where `just dev` listens.
set -eu

: "${DNSRULES_IP:=172.17.0.1}"

sed "s/@DNSRULES_IP@/${DNSRULES_IP}/g" \
    /etc/unbound/unbound.conf.in > /etc/unbound/unbound.conf

exec unbound -d -c /etc/unbound/unbound.conf
