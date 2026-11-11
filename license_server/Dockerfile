FROM python:3.13-slim
WORKDIR /service
COPY license_server/requirements.txt /service/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home licensing
COPY license_server /service/license_server
COPY super_admin/__init__.py /service/super_admin/__init__.py
COPY super_admin/backend /service/super_admin/backend
COPY super_admin/frontend /service/super_admin/frontend
COPY licensing/__init__.py licensing/protocol.py /service/licensing/
USER licensing
EXPOSE 8000
CMD ["uvicorn", "license_server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=172.30.0.10", "--no-access-log"]
