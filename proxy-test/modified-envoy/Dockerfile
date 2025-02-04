FROM envoyproxy/envoy:v1.33.0

RUN apt-get update && apt-get install -y inotify-tools && apt-get install -y python3

COPY watch_envoy.sh /
COPY start_envoy.sh /
COPY hot-restarter.py /
COPY entrypoint.sh /

RUN chmod +x /watch_envoy.sh
RUN chmod +x /start_envoy.sh
RUN chmod +x /entrypoint.sh

USER envoy:envoy

ENTRYPOINT ["sh", "entrypoint.sh"]
