# Calibración de Homografía para Medición de Velocidad

## ¿Por qué calibrar?

El sistema necesita una **homografía** (transformación de perspectiva) para convertir el movimiento de los vehículos en el video a distancias reales en metros. Esto permite medir velocidades.

## Síntomas de que necesitas recalibrar:

- ✓ Se detectan vehículos pero **todas las velocidades son 0 km/h**
- ✓ El mensaje en consola dice: "Todos los vehículos están fuera del ROI"
- ✓ Cambiaste de video o cámara
- ✓ La perspectiva del video es diferente al video original de calibración

## Cómo calibrar paso a paso:

### 1. Asegúrate de tener un video de referencia
- El video debe mostrar una escena con vehículos moviéndose
- Debe ser del mismo ángulo/cámara que usarás para el análisis
- Idealmente con marcas de distancia conocidas en el suelo

### 2. Ejecuta el modo interactivo de calibración

```bash
cd backend
python TraficEye.py
```

### 3. Selecciona 4 puntos en el suelo

Cuando aparezca el video pausado:

1. **Clic en 4 puntos** que formen un rectángulo en el suelo (carretera)
   - Punto 1: Esquina superior izquierda
   - Punto 2: Esquina superior derecha
   - Punto 3: Esquina inferior derecha
   - Punto 4: Esquina inferior izquierda

2. Los puntos deben formar un **rectángulo en el suelo** (no en los edificios o cielo)

3. Presiona **ENTER** para confirmar, **ESC** para cancelar

### 4. Ajusta la escala métrica (opcional)

Si conoces una distancia real en el video:

1. Marca dos puntos con distancia conocida
2. Ingresa la distancia real en metros
3. El sistema ajustará la escala automáticamente

O simplemente presiona **ESC** para usar la escala por defecto.

### 5. Verifica que se guardó

Deberías ver el archivo:
```
backend/homography.npz
```

## Configuración del ROI

En `TraficEye.py` puedes ajustar:

```python
ROI_WIDTH_METERS = 7.0    # Ancho del ROI en metros
ROI_HEIGHT_METERS = 30.0  # Alto del ROI en metros (dirección del movimiento)
```

Estos valores representan las dimensiones reales del área de detección.

## Parámetros de velocidad ajustables

En `TraficEye.py`:

```python
SPEED_MIN_DISPLACEMENT_M = 0.2   # Mínimo avance para considerar (0.2m)
SPEED_MAX_DT_SEC = 1.0           # Tiempo máximo entre mediciones (1s)
SPEED_BASELINE_FRAMES = 5        # Frames entre mediciones (5)
SPEED_LIMIT_KMH = 85.0           # Límite de velocidad por defecto
```

## Tips importantes:

- Los 4 puntos deben estar en el **suelo**, no en objetos verticales
- Mientras más grande el ROI, mejor la precisión
- Los vehículos solo se miden cuando están **dentro del ROI**
- Recalibra si cambias de video o ángulo de cámara
- Si sigues teniendo problemas, verifica que el video tenga movimiento claro

## Solución de problemas:

### "No se pudo cargar homography.npz"
```bash
cd backend
python TraficEye.py  # Recalibra desde cero
```

### "Todos los vehículos fuera del ROI"
- El ROI es muy pequeño o está en la posición incorrecta
- Recalibra seleccionando un área más grande donde pasan los vehículos

### "Velocidades muy bajas o muy altas"
- Ajusta `METRIC_SCALE_M` en la calibración
- Verifica que los 4 puntos formen un rectángulo correcto
- Usa la calibración de escala con una distancia conocida

## Ejemplo visual:

```
Video original               Vista desde arriba (ROI)
┌─────────────┐              ┌──────────┐
│    /  \     │              │          │
│   /____\    │    =====>    │ 7m x 30m │
│  1─────2    │              │          │
│  │ ROI │    │              │          │
│  4─────3    │              └──────────┘
└─────────────┘              (Vista métrica)
```

Los vehículos que pasen por el área 1-2-3-4 tendrán su velocidad medida.
