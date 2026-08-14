FROM archlinux:latest

RUN pacman -Sy --noconfirm unbound bind && pacman -Scc --noconfirm

COPY unbound.conf /etc/unbound/unbound.conf.in
COPY rpz-test.zone /etc/unbound/rpz-test.zone
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 53/udp 53/tcp 8953/tcp

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
