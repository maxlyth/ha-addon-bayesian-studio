ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY rootfs /

# Bump VERSION on every release — busts the layer cache for the COPY below and sets the runtime version
ARG VERSION=0.4.11
ENV VERSION=${VERSION}
COPY bayesian_studio /app/bayesian_studio/
COPY .streamlit /app/.streamlit/

WORKDIR /app
