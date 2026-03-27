ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY rootfs /

# Cache-bust: bump this when Python source changes must be force-recopied
ARG CACHEBUST=0.1.9
COPY bayesian_studio /app/bayesian_studio/

WORKDIR /app
