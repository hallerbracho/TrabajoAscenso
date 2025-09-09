# Usa una imagen base oficial de Python. Se elige la versión 'slim' por ser más ligera.
FROM python:3.11-slim

# Establece el directorio de trabajo dentro del contenedor.
WORKDIR /app

# Copia primero el archivo de requerimientos para aprovechar la caché de Docker.
# La capa de dependencias solo se reconstruirá si este archivo cambia.
COPY requirements.txt .

# Instala las dependencias de Python especificadas en requirements.txt.
# --no-cache-dir reduce el tamaño final de la imagen.
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto del código de la aplicación al directorio de trabajo.
COPY clasesluz.py .

# Expone el puerto 8501, que es el puerto por defecto de Streamlit.
EXPOSE 8501

# El comando para ejecutar la aplicación cuando se inicie el contenedor.
# --server.address=0.0.0.0 permite que la aplicación sea accesible desde fuera del contenedor.
CMD ["streamlit", "run", "clasesluz.py", "--server.port=8501", "--server.address=0.0.0.0"]