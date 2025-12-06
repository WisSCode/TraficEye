# TrafficEye — Detección de exceso de velocidad y registro de infracciones

Aplicación full-stack para analizar videos de tráfico, medir velocidades y registrar infracciones. El flujo está unificado en una sola página: subir video → calibración (perspectiva y métrica) → análisis → resultados. Los resultados incluyen video procesado, CSV y PDF.

## Características clave
- Página de Proceso unificada (upload, calibración y análisis en un solo lugar).
- Resultados por trabajo (job) en `backend/outputs/<job_id>/` (video `processed.mp4` y `violations.csv`).
- Re-codificación opcional a H.264/AAC con FFmpeg para compatibilidad de video en navegador.
- Registro de infracciones solo si la velocidad supera el límite durante un tiempo sostenido (anti-outliers).
- Métricas robustas: el dashboard muestra Velocidad promedio (avgSpeed) y cuenta de infracciones/vehículos.

## Requisitos
- Windows y Linux:
  - Python 3.9–3.10
  - Node.js 18+ y npm
  - (Opcional) FFmpeg en PATH para recodificar video a H.264/AAC
  - GPU no obligatoria (modelo ligero YOLO), pero acelera en Linux con CUDA si está disponible

## Estructura
```bash 
backend/               # API FastAPI + análisis (YOLO + Norfair + OpenCV)
  api.py               # Endpoints REST
  TraficEye.py         # Lógica de detección, tracking y velocidades
  outputs/             # Artefactos por job (video/csv)
  uploads/             # Subidas temporales por job
  videos/              # Videos de ejemplo (opcional)
frontend/              # React + Vite
  src/components/      # Process.jsx (flujo) y Dashboard.jsx (resultados)
README.md              # (este archivo)
```

## Puesta en marcha rápida
### Backend (FastAPI)

```bash
cd backend
pip install -r requirements.txt
python main.py
```
Servirá en `http://localhost:8000`.

### Frontend (Vite + React)

```bash
cd frontend
npm ci
npm run dev
```
- Vite abre `http://localhost:5173`.
- Si el backend corre en otra URL, crea `.env` en `frontend/` con:
  ```ini
  VITE_API_URL=http://127.0.0.1:8000
  ```

## Flujo de uso
1. Subir video y (opcionalmente) cargar un frame de calibración (perspectiva y escala métrica).
2. Iniciar análisis indicando el límite de velocidad (km/h).
3. El backend procesa y expone `status` y `result` por `job_id`.
4. Al finalizar, la UI redirige a Resultados y muestra:
   - Video procesado (si está disponible y compatible).
   - Tabla CSV de infracciones descargable.
   - PDF con resumen.
   - Métricas: vehículos, infracciones y velocidad promedio (avgSpeed).

## Endpoints principales (resumen)
- `POST /api/analyze` — Inicia análisis. Acepta `speed_limit` y `video` o `video_path`.
- `GET  /api/status/{job_id}` — Progreso y estado. Incluye `result` al completar.
- `GET  /api/result/{job_id}/video` — Descarga/stream del video procesado.
- `GET  /api/result/{job_id}/csv` — CSV de infracciones.
- `GET  /api/result/{job_id}/report` — PDF resumen.
- Calibración:
  - `GET  /api/calibration/status` — Homografía guardada sí/no.
  - `GET  /api/calibration/frame` — Frame JPEG para marcar puntos.
  - `POST /api/calibration/save` — Guarda homografía (4 puntos + dimensiones ROI).
  - `POST /api/calibration/metric_scale` — Calcula/guarda escala métrica (2 puntos + distancia conocida).

## Lógica de infracciones y cálculo de velocidad
- Detección: Ultralytics YOLO (`yolo11n.pt`) identifica vehículos y su clase.
- Tracking: Norfair asigna IDs persistentes a cada vehículo por distancia euclídea del punto.
- Calibración: Homografía con 4 puntos para transformar al plano métrico; escala métrica con 2 puntos y distancia conocida.
- Velocidad: se calcula a partir del desplazamiento longitudinal homografiado entre frames y se suaviza con ventana.
- Anti-outliers: se exige tiempo sostenido sobre el límite (`VIOLATION_MIN_DURATION_SEC`, p. ej. 1.0 s) y se reporta velocidad promedio.
- Por defecto, una infracción se registra si el vehículo supera el límite durante un tiempo sostenido (`VIOLATION_MIN_DURATION_SEC`, default 1.0 s) para mitigar picos de una sola lectura.
- En `backend/TraficEye.py`:
  - Ajusta `VIOLATION_MIN_DURATION_SEC` para ser más/menos estricto.
  - La velocidad promedio (`avgSpeed`) se calcula promediando el historial por vehículo y luego el promedio global.
  - La velocidad máxima interna usa percentil 95 para diagnóstico, pero la UI muestra `avgSpeed`.

## Compatibilidad de video (FFmpeg)
- El pipeline intenta escribir con codecs compatibles. Si el códec final fue `mp4v`, el backend recodifica a H.264/AAC si FFmpeg está disponible.
- Si el navegador no reproduce el video:
  - Instala FFmpeg y vuelve a ejecutar el análisis.
  - Siempre podrás descargar el CSV y el PDF aunque falte el video.

## Artefactos de salida
- Por cada análisis: `backend/outputs/<job_id>/`
  - `processed.mp4` — Video con cajas e información.
  - `violations.csv` — Tabla de infracciones.
- La API hace fallback directo al filesystem para servirlos incluso tras reinicios.

## Herramientas y técnicas usadas
- Ultralytics YOLO: detección y clasificación de vehículos.
- Norfair: seguimiento multi-objeto y asignación de IDs.
- OpenCV: IO de video, homografía, transformaciones y overlays.
- FastAPI/Starlette: API REST asíncrona para upload, calibración y resultados.
- FPDF: generación del PDF resumen.
- FFmpeg: recodificación H.264/AAC y `+faststart` para streaming.
- React + Vite: UI de proceso unificado y dashboard de resultados.
- El frontend persiste el último `result` en `localStorage` como `trafficEyeResult` para hidratar al visitar `/results`.
- Las clases detectadas por defecto incluyen: `car`, `truck`, `bus`, `motorbike/motorcycle`, `bicycle` (ajustable en `TraficEye.py`).

## Solución de problemas
### Windows
- Instala FFmpeg: `winget install FFmpeg` o descarga oficial.
- Si Anaconda/venv: activa el entorno antes de `pip install -r requirements.txt`.
### Linux (Debian/Ubuntu)
- Instala FFmpeg: `sudo apt update && sudo apt install ffmpeg`.
- Si usas CUDA/cuDNN, instala drivers y versión de `ultralytics`/`torch` compatible.
- El video no se reproduce: instala FFmpeg o usa un video con H.264/AAC.
- Sin medición: verifica que el `footpoint` esté dentro del ROI calibrado y que exista `homography.npz`.
- Velocidades irreales: ajusta homografía/escala métrica; el sistema ya usa suavizado y percentiles, y requiere duración sostenida para infracciones.