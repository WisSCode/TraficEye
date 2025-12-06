# Backend (FastAPI) — Resumen rápido

Consulta la guía completa en `../README.md`.

## Arranque
```cmd
cd backend
pip install -r requirements.txt
python main.py
```
Sirve en `http://localhost:8000`.

## Endpoints
- `POST /api/analyze` (FormData: `speed_limit`, `video` o `video_path`)
- `GET  /api/status/{job_id}`
- `GET  /api/result/{job_id}/video|csv|report`
- Calibración: `GET /api/calibration/frame`, `POST /api/calibration/save`, `POST /api/calibration/metric_scale`

## Notas
- Infracción requiere tiempo sostenido sobre el límite (`VIOLATION_MIN_DURATION_SEC`).
- FFmpeg opcional para recodificar video a H.264.
