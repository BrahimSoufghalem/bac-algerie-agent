FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
COPY deploy/python-sandbox/requirements.txt /sandbox/requirements.txt
RUN pip install --no-cache-dir -r /sandbox/requirements.txt
COPY bac/science/python_child.py /sandbox/child.py
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT ["python", "-I", "/sandbox/child.py"]
