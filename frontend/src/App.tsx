import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import { Loading } from "./components/ui";
import Shell from "./components/Shell";
import LoginPage from "./routes/LoginPage";
import CasesPage from "./routes/CasesPage";
import UploadPage from "./routes/UploadPage";
import ReviewPage from "./routes/ReviewPage";

function Gate() {
  const { user, ready } = useAuth();
  if (!ready) return <Loading />;
  if (!user) return <LoginPage />;
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Navigate to="/cases" replace />} />
        <Route path="/cases" element={<CasesPage />} />
        <Route path="/cases/:caseId/documents" element={<UploadPage />} />
        <Route path="/cases/:caseId/review" element={<ReviewPage />} />
        <Route path="*" element={<Navigate to="/cases" replace />} />
      </Routes>
    </Shell>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </BrowserRouter>
  );
}
