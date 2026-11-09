# Dependência face-recognition

Não adicione `face-recognition` ao `requirements.txt`. O Dockerfile instala essa biblioteca separadamente com `--no-deps`, usando `dlib-bin` pré-compilado para evitar que o pip tente compilar `dlib` no ambiente do Hugging Face.
