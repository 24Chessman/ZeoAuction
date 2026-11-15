FROM nginx:1.27-alpine

COPY infra/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY infra/nginx/proxy_params /etc/nginx/proxy_params
COPY infra/nginx/entrypoint.sh /usr/local/bin/zeo-nginx-entrypoint
RUN chmod +x /usr/local/bin/zeo-nginx-entrypoint

EXPOSE 80

ENTRYPOINT ["/usr/local/bin/zeo-nginx-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
