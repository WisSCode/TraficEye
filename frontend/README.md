# Frontend (Vite + React) — Resumen rápido

La guía completa está en `../README.md`.

## Desarrollo
```cmd
cd frontend
npm ci
npm run dev
```
- Por defecto, la API se asume en `http://127.0.0.1:8000`.
- Para cambiarlo, crea `.env` con:
	```ini
	VITE_API_URL=http://127.0.0.1:8000
	```

## Páginas
- Proceso: flujo unificado de carga → calibración → análisis.
- Resultados: muestra video, CSV/PDF y métricas (velocidad promedio).
