FROM python:3
RUN pip --no-cache-dir install  pipenv
COPY . /app
WORKDIR /app
RUN pipenv install
EXPOSE 5000
ENV FLASK_APP=main.py
CMD ["pipenv", "run", "flask", "run", "-h", "0.0.0.0"]
