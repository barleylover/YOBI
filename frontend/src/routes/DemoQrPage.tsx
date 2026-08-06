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
    <main className="center-page">
      <section className="qr-card">
        <p className="eyebrow">Live demo entry</p>
        {png ? (
          <img className="qr-image" src={png} alt={`QR code for ${target}`} />
        ) : (
          <div className="qr-placeholder">YOBI<br />QR</div>
        )}
        <h1>Scan to meet YOBI</h1>
        <p>This code always points to the current deployment origin.</p>
        <code className="qr-url">{target}</code>
        {svg && (
          <a className="secondary-button qr-download" href={svg} download="yobi-demo-qr.svg">
            Download presentation SVG
          </a>
        )}
      </section>
    </main>
  );
}
