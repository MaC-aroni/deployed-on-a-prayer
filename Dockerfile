# One image for Fly: build the frontend, then serve it and the API from FastAPI.
# Versions match mise.toml.
FROM node:22.23.4-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12.16-slim
# The MaC runner checks out repos with git and runs Terraform. Keep the version equal to mise.toml.
ARG TERRAFORM_VERSION=1.17.1
ARG TARGETARCH
RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl unzip ca-certificates \
 && cd /tmp \
 && arch="${TARGETARCH:-amd64}" \
 && base="https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}" \
 && curl -fsSLO "${base}/terraform_${TERRAFORM_VERSION}_linux_${arch}.zip" \
 && curl -fsSLO "${base}/terraform_${TERRAFORM_VERSION}_SHA256SUMS" \
 && sha256sum --check --ignore-missing "terraform_${TERRAFORM_VERSION}_SHA256SUMS" \
 && unzip -q "terraform_${TERRAFORM_VERSION}_linux_${arch}.zip" -d /usr/local/bin \
 && rm -f terraform_* \
 && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
 && terraform version
WORKDIR /app
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
# Migrations the API lists (MAC_MIGRATIONS_DIR). Later this will be the mac-migrations repo.
COPY examples/ examples/
COPY --from=frontend /app/frontend/dist frontend/dist
WORKDIR /app/backend
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
