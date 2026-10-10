FROM docker:28-cli
RUN apk add --no-cache python3
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY bac/science/sandbox_broker.py /broker.py
CMD ["python3", "-I", "/broker.py"]
