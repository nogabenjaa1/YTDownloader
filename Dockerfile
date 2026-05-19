# Usamos una versión ligera y muy estable de Python
FROM python:3.11-slim

# ¡AQUI ESTÁ LA MAGIA! Instalamos ffmpeg directamente en el sistema operativo de la nube
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Le decimos a la nube dónde vamos a trabajar
WORKDIR /app

# Copiamos los requisitos y los instalamos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el resto de tu código (tu app.py y tu carpeta static)
COPY . .

# Exponemos el puerto 8080 que configuraste en Railway
EXPOSE 8080

# El Start Command nativo (Railway ya no lo necesitará en su panel)
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080"]