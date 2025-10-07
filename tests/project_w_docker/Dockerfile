ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# Test updating the base image so we know that the certs are working
RUN apt-get update && apt-get install -y python3 python3-pip

RUN mkdir -p /artifacts
RUN touch /artifacts/test.txt

# meaningless command
RUN ls -la

COPY test_script.sh /test_script.sh
RUN chmod +x /test_script.sh
