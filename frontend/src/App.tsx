import { Navigate, Route, Routes } from "react-router-dom";
import { ChatPage } from "./routes/ChatPage";
import { HandoffPage } from "./routes/HandoffPage";
import { OnboardingPage } from "./routes/OnboardingPage";
import { LocalePage } from "./routes/LocalePage";
import { WelcomePage } from "./routes/WelcomePage";

export default function App() {
  return (
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
  );
}
