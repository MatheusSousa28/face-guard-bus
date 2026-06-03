#Usa uma imagem oficial do Python, leve, mas com base Debian
FROM python:3.10-slim

#Instala os compiladores em C++ e dependências do sistema para o dlib e OpenCV
RUN apt-get update && apt-get install -y \
    cmake \
    g++ \
    make \
    libopenblas-dev \
    liblapack-dev \
    libjpeg-dev \
    && rm -rf /var/lib/apt/lists/*

#Exigência do Hugging Face: Criar um usuário não-root com ID 1000
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

#Define a pasta de trabalho
WORKDIR /app

#Copia o código para dentro do container, dando posse ao usuário
COPY --chown=user . /app

# Atualiza o instalador e baixa as dependências (dlib, face_recognition, django...)
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

#O Hugging expõe a porta 7860 por padrão
EXPOSE 7860

#Inicia o servidor Django escutando na porta correta
CMD ["python", "manage.py", "runserver", "0.0.0.0:7860"]