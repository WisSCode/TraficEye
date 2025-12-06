import { useEffect, useMemo, useRef, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Dashboard from "./components/Dashboard.jsx";
import Process from "./components/Process.jsx";

const allowedFormats = ["mp4", "avi", "mov", "mkv"];
const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

function App() {
  const [theme, setTheme] = useState("dark");
  const [speedLimit, setSpeedLimit] = useState("");
  const [videoFile, setVideoFile] = useState(null);
  const [errors, setErrors] = useState({});
  const [processing, setProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [analysisDone, setAnalysisDone] = useState(false);
  const [statusMessage, setStatusMessage] = useState("Carga los datos para iniciar el analisis.");
  const [processedVideoUrl, setProcessedVideoUrl] = useState("");
  const [csvUrl, setCsvUrl] = useState("");
  const [pdfUrl, setPdfUrl] = useState("");
  const pollRef = useRef(null);
  const [reportData, setReportData] = useState({
    infractions: [],
    metrics: {
      vehiclesDetected: 0,
      infractions: 0,
      maxSpeed: 0
    },
    speed_limit_kmh: null
  });

  const uploadPreviewUrl = useMemo(() => {
    if (!videoFile) return null;
    return URL.createObjectURL(videoFile);
  }, [videoFile]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    return () => {
      document.documentElement.removeAttribute("data-theme");
    };
  }, [theme]);

  useEffect(() => {
    return () => {
      if (uploadPreviewUrl) {
        URL.revokeObjectURL(uploadPreviewUrl);
      }
      if (pollRef.current) {
        clearInterval(pollRef.current);
      }
    };
  }, [uploadPreviewUrl]);

  const clearPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const validateInputs = () => {
    const validationErrors = {};
    if (!speedLimit || Number(speedLimit) <= 0) {
      validationErrors.speedLimit = "Ingresa una velocidad maxima valida.";
    }
    if (!videoFile) {
      validationErrors.video = "Carga un video en formato mp4, avi, mov o mkv.";
    } else {
      const extension = videoFile.name.split(".").pop()?.toLowerCase();
      if (!allowedFormats.includes(extension)) {
        validationErrors.video = "Formato no soportado. Usa mp4, avi, mov o mkv.";
      }
    }
    setErrors(validationErrors);
    return Object.keys(validationErrors).length === 0;
  };

  const startPolling = (jobId) => {
    const poll = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/status/${jobId}`);
        if (!response.ok) {
          throw new Error("No se pudo consultar el estado del analisis.");
        }
        const data = await response.json();
        setProgress(typeof data.progress === "number" ? data.progress : 0);
        setStatusMessage(data.message || "Procesando...");
        if (data.status === "completed") {
          clearPolling();
          const result = data.result || {};
          setReportData({
            infractions: result.infractions || [],
            metrics: result.metrics || { vehiclesDetected: 0, infractions: 0, maxSpeed: 0 },
            speed_limit_kmh: Number(result.speed_limit_kmh ?? speedLimit) || null
          });
          setProcessedVideoUrl(result.video_url ? `${API_BASE}${result.video_url}` : "");
          setCsvUrl(result.csv_url ? `${API_BASE}${result.csv_url}` : "");
          setPdfUrl(result.pdf_url ? `${API_BASE}${result.pdf_url}` : "");
          setProcessing(false);
          setAnalysisDone(true);
          setStatusMessage("Analisis completado y listo para ver.");
        } else if (data.status === "error") {
          clearPolling();
          setProcessing(false);
          setAnalysisDone(false);
          setStatusMessage(data.message || "Error en el backend durante el analisis.");
        }
      } catch (error) {
        clearPolling();
        setProcessing(false);
        setAnalysisDone(false);
        setStatusMessage(error.message || "No se pudo consultar el progreso.");
      }
    };

    poll();
    pollRef.current = setInterval(poll, 1500);
  };

  const handleStart = async () => {
    if (!validateInputs()) return;
    clearPolling();
    setProcessing(true);
    setProgress(0);
    setAnalysisDone(false);
    setReportData({
      infractions: [],
      metrics: { vehiclesDetected: 0, infractions: 0, maxSpeed: 0 },
      speed_limit_kmh: Number(speedLimit) || null
    });
    setProcessedVideoUrl("");
    setCsvUrl("");
    setPdfUrl("");
    setStatusMessage("Subiendo video al backend...");
    try {
      const formData = new FormData();
      formData.append("video", videoFile);
      formData.append("speed_limit", speedLimit);
      const response = await fetch(`${API_BASE}/api/analyze`, {
        method: "POST",
        body: formData
      });
      if (!response.ok) {
        throw new Error("No se pudo iniciar el analisis. Revisa que el backend este corriendo.");
      }
      const data = await response.json();
      setStatusMessage("Analisis iniciado en el backend...");
      startPolling(data.job_id);
    } catch (error) {
      setProcessing(false);
      setStatusMessage(error.message || "Error al iniciar el analisis.");
    }
  };

  const handleDownloadReport = () => {
    if (!analysisDone || !pdfUrl) return;
    const link = document.createElement("a");
    link.href = pdfUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.download = "reporte_infracciones.pdf";
    link.click();
  };

  return (
    <BrowserRouter>
      <div className={`app ${theme}`}>
        <header className="app-header">
          <h1>TrafficEye</h1>
          <p className="subtitle">Calibración, análisis y resultados en un solo UI</p>
          <nav className="nav">
            <NavLink to="/" className={({isActive})=>`pill-btn${isActive? ' active':''}`}>Proceso</NavLink>
            <NavLink to="/results" className={({isActive})=>`pill-btn${isActive? ' active':''}`}>Resultados</NavLink>
          </nav>
          <div className="header-actions">
            <button
              className="ghost-btn"
              type="button"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? "Modo claro" : "Modo oscuro"}
            </button>
          </div>
        </header>

        <main>
          <Routes>
            <Route path="/" element={<Process />} />
            <Route
              path="/results"
              element={
                <Dashboard
                  analysisDone={analysisDone}
                  processing={processing}
                  speedLimit={speedLimit}
                  videoUrl={processedVideoUrl}
                  videoName={videoFile?.name || ""}
                  csvUrl={csvUrl}
                  pdfUrl={pdfUrl}
                  reportData={reportData}
                  onDownloadReport={handleDownloadReport}
                />
              }
            />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
