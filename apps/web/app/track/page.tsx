import Link from "next/link";
import TrackingForm from "../../components/tracking-form";

export default function TrackPage() {
  return (
    <main className="shell narrow-shell">
      <header className="topbar">
        <Link className="brand" href="/">AI NETA</Link>
        <Link className="quiet-link" href="/">Wapas jaayein</Link>
      </header>
      <section className="page-heading" aria-labelledby="track-title">
        <p className="eyebrow">Receipt tracking</p>
        <h1 id="track-title">Apni shikayat ka haal dekhein</h1>
        <p className="lede">Receipt token wahi hai jo complaint submit hone par mila tha. Isse kisi ke saath public mein share na karein.</p>
      </section>
      <TrackingForm />
    </main>
  );
}
