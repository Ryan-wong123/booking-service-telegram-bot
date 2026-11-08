FROM alpine:3.20
RUN apk add --no-cache bash postgresql16-client aws-cli \
 && adduser -D -u 10001 backup
COPY backup.sh restore.sh /usr/local/bin/
USER 10001
ENTRYPOINT ["/usr/local/bin/backup.sh"]
