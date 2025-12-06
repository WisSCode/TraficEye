# Guía rápida para continuar el proyecto (backend + frontend)

## Estructura actual
- **backend/**
  - `TraficEye.py`: pipeline YOLO + Norfair + estimación de velocidad; función `analyze_video` reutilizable.
  - `api.py`: FastAPI con endpoints de análisis y descargas.
  - `uploads/`: donde se guardan los videos subidos.
  - `outputs/<job_id>/`: video procesado (`processed.mp4`) y `violations.csv`.
  - `homography.npz`: calibración necesaria para medir velocidades (debe existir).
  - `requirements.txt`: incluye FastAPI, uvicorn, fpdf2 y dependencias de visión.
- **frontend/**
  - Vite + React.
  - `src/App.jsx`: orquesta subida de video, consulta progreso y muestra resultados.
  - `src/components/DataEntry.jsx`: formulario (límite de velocidad + carga de video).
  - `src/components/Dashboard.jsx`: video procesado, métricas, tabla de infracciones, descargas CSV/PDF.

## API del backend
- `POST /api/analyze` (form-data: `video`, `speed_limit`): crea un job y arranca el análisis.
- `GET /api/status/{job_id}`: estado, progreso y, al completar, URLs de video/csv/pdf y métricas/infractions.
- `GET /api/result/{job_id}/video`: video procesado.
- `GET /api/result/{job_id}/csv`: CSV de infracciones.
- `GET /api/result/{job_id}/report`: PDF generado con las infracciones y métricas.

## Flujo de frontend (actual)
1. Sube video + límite -> `POST /api/analyze`.
2. Polling a `/api/status/{job_id}` hasta `completed`.
3. Muestra métricas, tabla con `infractions`, video procesado y links de descarga CSV/PDF.
4. El PDF se descarga directamente del backend (no se genera en el cliente).

## Requisitos previos
### FFmpeg (IMPORTANTE)
Para que los videos procesados se reproduzcan correctamente en el navegador, necesitas tener FFmpeg instalado:

#Instalación de FFmpeg
```bash
winget install FFmpeg

#Verifica la instalación:
```bash
ffmpeg -version
```

## Cómo correr
Backend:
```
cd backend
pip install -r requirements.txt
# Si no existe homography.npz, calibra una vez: python TraficEye.py (interactivo)
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```
Frontend:
```
cd frontend
set VITE_API_URL=http://localhost:8000   # PowerShell: $env:VITE_API_URL="http://localhost:8000"
npm install
npm run dev
```

## Notas clave
- **FFmpeg es necesario** para generar videos compatibles con navegadores web. Sin FFmpeg, los videos pueden no reproducirse.
- `analyze_video` usa `homography.npz`; si falta, el API fallará. Calibra en local y conserva el archivo.
- **IMPORTANTE**: Si las velocidades salen en 0.0, significa que necesitas recalibrar la homografía para tu video. Ver [CALIBRACION.md](CALIBRACION.md)
- El límite de velocidad se aplica en backend (`speed_limit`), y se recalcula `excess_kmh` en las respuestas.
- Si la lista `infractions` viene vacía, el backend intenta leer `violations.csv` para poblarla.
- Output del job: `outputs/<job_id>/processed.mp4`, `violations.csv`, y PDF generado en tiempo real al pedirlo.
- El sistema intenta usar códec H.264 (compatible con navegadores). Si no está disponible, usa mp4v y lo recodifica con FFmpeg automáticamente.
- El CSV se genera siempre (incluso vacío), y el PDF se puede descargar incluso sin infracciones.

## Siguientes pasos sugeridos
1) Persistencia: guardar jobs/metrics en BD (p. ej., SQLite/Postgres) en vez de solo en memoria.
2) Autenticación y control de acceso a descargas (video/CSV/PDF).
3) Manejo de colas y workers (Celery/RQ) para procesar múltiples videos en paralelo.
4) Validar y versionar `homography.npz` por cámara/escena; permitir subir una por API.
5) Añadir tests básicos: unit tests para `analyze_video` (mocks) y tests de API con `httpx`/`pytest`.
6) Observabilidad: logs estructurados y métricas (tiempo por job, FPS efectivo, infracciones detectadas).
