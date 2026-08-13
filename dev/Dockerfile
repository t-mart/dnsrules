FROM archlinux:latest

RUN pacman -Sy --noconfirm unbound bind && pacman -Scc --noconfirm

COPY unbound.conf /etc/unbound/unbound.conf
COPY rpz-test.zone /etc/unbound/rpz-test.zone

EXPOSE 53/udp 53/tcp 8953/tcp

CMD ["unbound", "-d", "-c", "/etc/unbound/unbound.conf"]
