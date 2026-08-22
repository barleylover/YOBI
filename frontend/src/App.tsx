import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

const WelcomePage = lazy(() => import("./routes/WelcomePage").then((module) => ({
  default: module.WelcomePage,
})));
const LocalePage = lazy(() => import("./routes/LocalePage").then((module) => ({
  default: module.LocalePage,
})));
const OnboardingPage = lazy(() => import("./routes/OnboardingPage").then((module) => ({
  default: module.OnboardingPage,
})));
const ChatPage = lazy(() => import("./routes/ChatPage").then((module) => ({
  default: module.ChatPage,
})));
const HandoffPage = lazy(() => import("./routes/HandoffPage").then((module) => ({
  default: module.HandoffPage,
})));

export default function App() {
  return (
    <Suspense fallback={(
      <main className="v2-screen subtle" role="status" aria-live="polite">
        <span className="visually-hidden">Loading YOBI</span>
      </main>
    )}>
      <Routes>
        <Route path="/" element={<WelcomePage />} />
        <Route path="/start" element={<LocalePage />} />
        <Route path="/profile" element={<OnboardingPage />} />
        <Route path="/chat/:sessionId" element={<ChatPage />} />
        <Route path="/handoff" element={<HandoffPage />} />
        <Route path="/pay/:checkoutId" element={<Navigate to="/handoff" replace />} />
        <Route path="/order/:orderId" element={<Navigate to="/handoff" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
