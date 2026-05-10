# syntax=docker/dockerfile:1.7
# Static React/Vite site served by nginx.
# Caller MUST run `npm run build` first so ./dist exists in build context.
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1

