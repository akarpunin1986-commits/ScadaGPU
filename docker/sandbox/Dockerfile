FROM python:3.12-slim

RUN pip install --no-cache-dir \
    openpyxl>=3.1 \
    matplotlib>=3.8 \
    pandas>=2.1 \
    httpx>=0.27 \
    psycopg2-binary>=2.9 \
    redis>=5.0 \
    Pillow>=10.0 \
    sqlalchemy>=2.0 \
    reportlab>=4.0 \
    fpdf2>=2.7

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV MPLBACKEND=Agg

RUN mkdir -p /output /workspace
WORKDIR /workspace

RUN useradd -m -s /bin/bash sandbox
RUN chown sandbox:sandbox /output /workspace
USER sandbox

COPY sandbox_runner.py /workspace/sandbox_runner.py

CMD ["python", "/workspace/sandbox_runner.py"]
