import { useEffect, useState } from "react";
import QRCode from "qrcode";

export function DemoQrPage() {
  const [png, setPng] = useState("");
  const [svg, setSvg] = useState("");
  const target = window.location.origin;

  useEffect(() => {
    void QRCode.toDataURL(target, {
      width: 360,
      margin: 2,
      color: { dark: "#24151f", light: "#ffffff" },
      errorCorrectionLevel: "M",
    }).then(setPng);
    void QRCode.toString(target, {
      type: "svg",
      margin: 2,
      color: { dark: "#24151f", light: "#ffffff" },
      errorCorrectionLevel: "M",
    }).then((source) =>
      setSvg(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(source)}`),
    );
  }, [target]);

  return (
    <main className="v2-screen subtle">
      <div className="v2-body" style={{ alignItems: "center", justifyContent: "center", gap: 14 }}>
        <section className="v2-summary-card" style={{ alignItems: "center", textAlign: "center", maxWidth: 340 }}>
          <img src="/figma/logo-mark.svg" alt="YOBI" width={44} height={44} />
          {png ? (
            <img src={png} alt={`QR code for ${target}`} style={{ width: 240, height: 240, borderRadius: 18 }} />
          ) : (
            <div style={{ width: 240, height: 240, borderRadius: 18, background: "var(--gray-100)" }} />
          )}
          <div className="v2-heading" style={{ alignItems: "center", textAlign: "center" }}>
            <h1 style={{ fontSize: 22 }}>Scan to meet YOBI</h1>
            <p>This code always points to the current deployment origin.</p>
          </div>
          <code style={{ padding: "8px 12px", borderRadius: 10, background: "var(--surface-subtle)", fontSize: 12, color: "var(--text-default)", overflowWrap: "anywhere" }}>{target}</code>
          {svg && (
            <a className="v2-cta compact secondary" style={{ textDecoration: "none", width: "100%" }} href={svg} download="yobi-demo-qr.svg">
              Download presentation SVG
            </a>
          )}
        </section>
      </div>
    </main>
  );
}
