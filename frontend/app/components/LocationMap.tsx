"use client";

import { useEffect, useMemo, useState } from "react";
import L from "leaflet";
import { GeoSearchControl, OpenStreetMapProvider } from "leaflet-geosearch";
import {
  MapContainer,
  Marker,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet-geosearch/dist/geosearch.css";

import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

type LatLng = { latitude: number; longitude: number };

type LocationMapProps = {
  latitude: number;
  longitude: number;
  onPositionChange: (lat: number, lng: number) => void;
  onConfirm: (lat: number, lng: number) => void;
};

const DEFAULT_POSITION: LatLng = {
  // Shivpuri, Madhya Pradesh
  latitude: 25.432,
  longitude: 77.6644,
};

// Fix default marker assets for Next.js bundling.
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x.src,
  iconUrl: markerIcon.src,
  shadowUrl: markerShadow.src,
});

function DraggablePin({
  position,
  onPositionChange,
}: {
  position: LatLng;
  onPositionChange: (lat: number, lng: number) => void;
}) {
  const [dragPos, setDragPos] = useState(position);

  useEffect(() => {
    setDragPos(position);
  }, [position.latitude, position.longitude]);

  useMapEvents({
    click(e) {
      const lat = e.latlng.lat;
      const lng = e.latlng.lng;
      setDragPos({ latitude: lat, longitude: lng });
      onPositionChange(lat, lng);
    },
  });

  return (
    <Marker
      draggable
      position={[dragPos.latitude, dragPos.longitude]}
      eventHandlers={{
        dragend: (event) => {
          const marker = event.target as L.Marker;
          const next = marker.getLatLng();
          setDragPos({ latitude: next.lat, longitude: next.lng });
          onPositionChange(next.lat, next.lng);
        },
      }}
    />
  );
}

function SearchControl({
  onPositionChange,
}: {
  onPositionChange: (lat: number, lng: number) => void;
}) {
  const map = useMap();

  useEffect(() => {
    const provider = new OpenStreetMapProvider();
    // leaflet-geosearch typings omit construct signature; cast for TS + Leaflet Control API
    const GeoSearchCtor = GeoSearchControl as unknown as new (opts: object) => L.Control;
    const searchControl = new GeoSearchCtor({
      provider,
      style: "bar",
      autoClose: true,
      retainZoomLevel: false,
      animateZoom: true,
      keepResult: true,
      marker: false,
      showMarker: false,
      searchLabel: "Search society, street, or area...",
    });

    map.addControl(searchControl);

    const handleShowLocation = (event: L.LeafletEvent) => {
      const loc = (event as L.LeafletEvent & { location?: { x?: number; y?: number } }).location;
      const lat = loc?.y;
      const lng = loc?.x;
      if (typeof lat === "number" && typeof lng === "number") {
        map.flyTo([lat, lng], Math.max(map.getZoom(), 16), { duration: 0.7 });
        onPositionChange(lat, lng);
      }
    };

    map.on("geosearch/showlocation", handleShowLocation);
    return () => {
      map.off("geosearch/showlocation", handleShowLocation);
      map.removeControl(searchControl);
    };
  }, [map, onPositionChange]);

  return null;
}

export default function LocationMap({
  latitude,
  longitude,
  onPositionChange,
  onConfirm,
}: LocationMapProps) {
  const initialCenter = useMemo(
    () => [DEFAULT_POSITION.latitude, DEFAULT_POSITION.longitude] as [number, number],
    []
  );

  const [readyPos, setReadyPos] = useState<LatLng>({
    latitude,
    longitude,
  });

  const handlePositionChange = (lat: number, lng: number) => {
    setReadyPos({ latitude: lat, longitude: lng });
    onPositionChange(lat, lng);
  };

  useEffect(() => {
    if (latitude && longitude) {
      setReadyPos({ latitude, longitude });
      return;
    }

    if (!navigator.geolocation) {
      setReadyPos(DEFAULT_POSITION);
      handlePositionChange(DEFAULT_POSITION.latitude, DEFAULT_POSITION.longitude);
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lat = position.coords.latitude;
        const lng = position.coords.longitude;
        handlePositionChange(lat, lng);
      },
      () => {
        handlePositionChange(DEFAULT_POSITION.latitude, DEFAULT_POSITION.longitude);
      },
      {
        enableHighAccuracy: true,
        timeout: 8000,
        maximumAge: 0,
      }
    );
  }, [latitude, longitude, onPositionChange]);

  return (
    <div className="rounded-xl border border-gray-300 bg-white p-3 shadow-sm">
      <div className="mb-2 text-sm text-gray-700">
        Upar search se society/street dhundo (OpenStreetMap), zarurat ho to pin drag karein, phir{" "}
        <strong>Confirm Location</strong>.
      </div>
      <div className="h-64 w-full overflow-hidden rounded-lg border border-gray-200">
        <MapContainer
          center={initialCenter}
          zoom={13}
          style={{ height: "100%", width: "100%" }}
          scrollWheelZoom
        >
          <SearchControl onPositionChange={handlePositionChange} />
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <DraggablePin position={readyPos} onPositionChange={handlePositionChange} />
        </MapContainer>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <div className="text-xs text-gray-600">
          Lat: {readyPos.latitude.toFixed(6)} | Lng: {readyPos.longitude.toFixed(6)}
        </div>
        <button
          type="button"
          onClick={() => onConfirm(readyPos.latitude, readyPos.longitude)}
          className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700"
        >
          Confirm Location
        </button>
      </div>
    </div>
  );
}

