import { Navigate, useLocation } from "react-router-dom";

export function LocalePage() {
  const location = useLocation();
  return <Navigate to={`/${location.search}`} replace />;
}
