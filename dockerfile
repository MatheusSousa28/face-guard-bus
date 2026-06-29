FROM python:3.10-slim

RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

COPY --chown=user requirements.txt /app/

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --no-cache-dir --no-deps face_recognition==1.3.0

COPY --chown=user . /app

RUN python manage.py collectstatic --noinput

EXPOSE 7860
CMD ["python", "manage.py", "runserver", "0.0.0.0:7860"]