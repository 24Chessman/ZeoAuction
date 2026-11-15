#!/bin/sh
set -eu

envsubst '${AUTH_USER_URL} ${KYC_URL} ${AUCTION_URL} ${BID_URL} ${PRICING_URL} ${PAYMENT_URL} ${DISPUTE_URL} ${SEARCH_URL} ${ADMIN_URL} ${WS_GATEWAY_URL}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

exec "$@"
