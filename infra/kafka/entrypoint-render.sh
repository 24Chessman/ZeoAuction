#!/bin/sh
# Render entrypoint for the Kafka private service (owner: Ayush, #89).
# Sets the single-node KRaft configuration, then hands over to the image's own launcher.
# KAFKA_ADVERTISED_HOST must be the service's internal Render hostname (see render.yaml);
# it is what every other service puts in KAFKA_BOOTSTRAP_SERVERS.
set -eu

: "${KAFKA_ADVERTISED_HOST:?set KAFKA_ADVERTISED_HOST to the Render internal hostname}"

export KAFKA_NODE_ID="${KAFKA_NODE_ID:-1}"
export KAFKA_PROCESS_ROLES="broker,controller"
export KAFKA_LISTENERS="PLAINTEXT://:9092,CONTROLLER://:9093"
export KAFKA_ADVERTISED_LISTENERS="PLAINTEXT://${KAFKA_ADVERTISED_HOST}:9092"
export KAFKA_LISTENER_SECURITY_PROTOCOL_MAP="CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT"
export KAFKA_CONTROLLER_QUORUM_VOTERS="1@localhost:9093"
export KAFKA_CONTROLLER_LISTENER_NAMES="CONTROLLER"
export KAFKA_INTER_BROKER_LISTENER_NAME="PLAINTEXT"
export KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1
export KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1
export KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1
export KAFKA_AUTO_CREATE_TOPICS_ENABLE=false
# Data lives on the persistent disk so messages and offsets survive restarts and deploys.
export KAFKA_LOG_DIRS="/var/lib/kafka/data"

exec /etc/kafka/docker/run
