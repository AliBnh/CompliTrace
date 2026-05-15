ARG FRONTEND_BASE_IMAGE=node:20-alpine
FROM ${FRONTEND_BASE_IMAGE}

WORKDIR /app

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY}

COPY apps/frontend/package*.json ./
RUN npm install

COPY apps/frontend/ ./

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
