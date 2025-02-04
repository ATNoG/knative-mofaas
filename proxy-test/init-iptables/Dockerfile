FROM alpine:3.21

RUN apk update && apk add iptables

COPY entrypoint.sh /
RUN chmod +x entrypoint.sh

ENTRYPOINT ["sh", "entrypoint.sh"]
