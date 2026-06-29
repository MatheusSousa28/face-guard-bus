FROM animcogn/face_recognition:python3.9-slim

RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

# 3. Define a pasta de trabalho
WORKDIR /app

# 4. Copia os requerimentos
COPY --chown=user requirements.txt /app/

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copia o resto do código do seu projeto
COPY --chown=user . /app

RUN python manage.py collectstatic --noinput

CMD ["python", "manage.py", "runserver", "0.0.0.0:7860"]