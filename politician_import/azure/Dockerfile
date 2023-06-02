FROM mcr.microsoft.com/azure-functions/python:4-python3.10

# 0. Install essential packages
RUN apt-get update \
    && apt-get install -y \
        build-essential \
        cmake \
        git \
        wget \
        unzip \
        unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

# 1. Copy python code to image
COPY . /home/site/wwwroot

# 2. Install packages in requirements.txt
RUN cd /home/site/wwwroot && \
    pip install -r requirements.txt

# 3. Copy missing cert to certifi pem file
RUN cat /home/site/wwwroot/missing_cert.pem >> /usr/local/lib/python3.10/site-packages/certifi/cacert.pem

