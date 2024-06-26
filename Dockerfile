# app/Dockerfile

FROM python:3.10-slim

WORKDIR /app

ADD . /app

RUN pip install -r requirements.txt


EXPOSE 8501

CMD streamlit run index.py --server.port=8501