ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# Test updating the base image so we know that the certs are working
RUN apt-get update && apt-get install -y python3 python3-pip

# meaningless command
RUN ls -la
