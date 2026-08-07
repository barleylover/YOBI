import { Navigate, Route, Routes } from "react-router-dom";
import { ChatPage } from "./routes/ChatPage";
import { DemoControlPage } from "./routes/DemoControlPage";
import { DemoQrPage } from "./routes/DemoQrPage";
import { OnboardingPage } from "./routes/OnboardingPage";
import { LocalePage } from "./routes/LocalePage";
import { OrderPage } from "./routes/OrderPage";
import { PaymentPage } from "./routes/PaymentPage";
import { WelcomePage } from "./routes/WelcomePage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<WelcomePage />} />
      <Route path="/start" element={<LocalePage />} />
      <Route path="/profile" element={<OnboardingPage />} />
      <Route path="/chat/:sessionId" element={<ChatPage />} />
      <Route path="/pay/:checkoutId" element={<PaymentPage />} />
      <Route path="/order/:orderId" element={<OrderPage />} />
      <Route path="/demo/qr" element={<DemoQrPage />} />
      <Route path="/demo/control" element={<DemoControlPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
