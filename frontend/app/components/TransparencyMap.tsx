"use client";

import { useMemo } from "react";
import L from "leaflet";
import { MapContainer, Marker, Popup, TileLayer } from "react-leaflet";
import "leaflet/dist/leaflet.css";

export type PublicComplaint = {
  complaint_id: string;
  latitude: number;
  longitude: number;
  issue_type: string;
  department_name: string;
  status: string;
};

function issueColor(issueType: string): string {
  const t = (issueType || "").toLowerCase();
  if (t.includes("water") || t.includes("pani") || t.includes("jal")) return "#2563eb"; // blue
  if (t.includes("road") || t.includes("sadak") || t.includes("pwd")) return "#6b7280"; // gray
  if (t.includes("electric") || t.includes("bijli") || t.includes("power")) return "#eab308"; // yellow
  if (t.includes("sanitation") || t.includes("garbage") || t.includes("safai")) return "#16a34a"; // green
  return "#0f766e"; // teal default
}

function markerIcon(color: string): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<span style="display:block;width:14px;height:14px;border-radius:9999px;background:${color};border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.5)"></span>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

function statusLabel(status: string): string {
  const s = (status || "").toLowerCase();
  if (s === "in_progress") return "In Progress";
  if (s === "resolved") return "Resolved";
  if (s === "pending") return "Pending";
  if (s === "submitted") return "Submitted";
  return status || "Unknown";
}

export default function TransparencyMap({ complaints }: { complaints: PublicComplaint[] }) {
  const center = useMemo<[number, number]>(() => {
    if (complaints.length === 0) return [23.5937, 78.9629]; // India center fallback
    const avgLat = complaints.reduce((sum, c) => sum + c.latitude, 0) / complaints.length;
    const avgLng = complaints.reduce((sum, c) => sum + c.longitude, 0) / complaints.length;
    return [avgLat, avgLng];
  }, [complaints]);

  return (
    <div className="h-[28rem] w-full overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm sm:h-[34rem]">
      <MapContainer center={center} zoom={6} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {complaints.map((item) => (
          <Marker
            key={item.complaint_id}
            position={[item.latitude, item.longitude]}
            icon={markerIcon(issueColor(item.issue_type))}
          >
            <Popup>
              <div className="min-w-[180px]">
                <p className="text-xs font-semibold text-slate-900">Issue: {item.issue_type || "General"}</p>
                <p className="mt-1 text-xs text-slate-700">
                  Department: {item.department_name || "Municipal Helpdesk"}
                </p>
                <p className="mt-1 text-xs text-slate-700">Status: {statusLabel(item.status)}</p>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}
