# Kafka broker for Render (owner: Ayush, #89).
# Render has no managed Kafka, so the broker runs as a private service with a persistent disk
# mounted at /var/lib/kafka/data (render.yaml). Single broker, KRaft mode, no ZooKeeper.
# Fallback if this proves unreliable: an external managed cluster (documented in ADR-0012).
FROM apache/kafka:3.8.1

USER root
COPY entrypoint-render.sh /usr/local/bin/entrypoint-render.sh
COPY create-topics.sh smoke-test.sh /opt/zeo/
RUN chmod +x /usr/local/bin/entrypoint-render.sh /opt/zeo/*.sh
# Stays root: Render mounts the persistent disk root-owned, and the image's appuser cannot
# write to it. Acceptable for a private service with no public port.

ENTRYPOINT ["/usr/local/bin/entrypoint-render.sh"]
