FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pandas \
    && ln -s /usr/bin/python3 /usr/bin/python && rm -rf /var/lib/apt/lists/*
WORKDIR /work
