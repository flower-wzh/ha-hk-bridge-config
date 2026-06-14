ARG BUILD_FROM=ghcr.io/hassio-addons/base:16.3.1
FROM $BUILD_FROM

ENV LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apk add --no-cache python3 py3-pip py3-yaml
RUN pip3 install --break-system-packages --no-cache-dir flask==3.0.3 requests==2.32.3

COPY rootfs /

RUN chmod a+x /etc/services.d/app/run

# Healthcheck (Ingress 模式下,curl / 应该返回 200)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8099/ || exit 1

LABEL io.hass.name="HomeKit Bridge 配置器" \
      io.hass.description="可视化调整 HA 的 HomeKit Bridge 配置" \
      io.hass.type="addon" \
      io.hass.version="1.0.0"
