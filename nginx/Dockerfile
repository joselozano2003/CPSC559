FROM nginx:alpine
RUN apk add --no-cache python3 py3-pip && pip install flask --break-system-packages
COPY nginx.conf /etc/nginx/nginx.conf
COPY upstream.conf /etc/nginx/upstream.conf
COPY updater.py /updater.py
COPY start.sh /start.sh
RUN chmod +x /start.sh
CMD ["/start.sh"]
