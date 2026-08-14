import Link from "next/link";

export default function HomePage() {
  return (
    <main className="shell">
      <header className="topbar">
        <Link className="brand" href="/" aria-label="AI Neta home">AI NETA</Link>
        <div className="topbar-links"><Link className="quiet-link" href="/transparency">Hisaab dekhein</Link><Link className="quiet-link" href="/track">Shikayat dekhein</Link><Link className="quiet-link" href="/admin">Operator/admin panel</Link></div>
      </header>

      <section className="hero" aria-labelledby="hero-title">
        <p className="eyebrow">Aapki baat. Aapka haq.</p>
        <h1 id="hero-title">Shehar ki dikkat ko record karein, phir uska haal dekhein.</h1>
        <p className="lede">
          AI Neta aapki civic complaint ko samajhne, sahi jagah tak pahunchane aur
          uski progress dikhane ke liye bana hai.
        </p>
        <div className="actions">
          <Link className="button button-primary" href="/file">Login / account se shuru karein</Link>
          <Link className="button button-primary" href="/track">Receipt se status dekhein</Link>
          <a className="button button-secondary" href="aineta://">Mobile app kholein</a>
        </div>
      </section>

      <section className="feature-grid" aria-label="AI Neta ke fayde">
        <article className="card"><span className="icon" aria-hidden="true">🔎</span><h2>Saaf status</h2><p>Receipt token se wahi public-safe update dikhega jo share karna zaroori hai.</p></article>
        <article className="card"><span className="icon" aria-hidden="true">🛡️</span><h2>Private receipt</h2><p>Public page par aapka naam, raw description ya exact location nahi dikhayi jaati.</p></article>
        <article className="card"><span className="icon" aria-hidden="true">🎙️</span><h2>Voice-first filing</h2><p>Mobile app trusted capture ke liye, aur browser filing review-gated photo, location aur voice support ke liye bani hai.</p></article>
      </section>

      <footer className="footer">AI Neta neutral civic help hai — political campaign ya legal advice nahi.</footer>
    </main>
  );
}
