# app/Dockerfile

FROM python:3.10-slim

WORKDIR /app

ADD . /app

RUN pip install -r requirements.txt


EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

CMD streamlit run index.py --server.port=8501