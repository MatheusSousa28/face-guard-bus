FROM animcogn/face_recognition:python3.9-slim

RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

COPY --chown=user requirements.txt /app/

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . /app

RUN python manage.py collectstatic --noinput

EXPOSE 7860
CMD ["python", "manage.py", "runserver", "0.0.0.0:7860"]