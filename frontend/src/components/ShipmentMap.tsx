"use client";

import { Fragment } from "react";
import { MapContainer, TileLayer, Polyline, CircleMarker, Tooltip } from "react-leaflet";
import "leaflet/dist/leaflet.css";

export interface TrackLeg {
  leg_id: string;
  mode: string;
  color: string;
  origin: string;
  destination: string;
  coords: { lat: number; lon: number }[];
}

export default function ShipmentMap({ tracks }: { tracks: TrackLeg[] }) {
  if (!tracks.length) {
    return <div className="p-6 text-center text-xs text-slate-500">No mappable facilities.</div>;
  }
  const all = tracks.flatMap((t) => t.coords);
  const center: [number, number] = [
    all.reduce((s, c) => s + c.lat, 0) / all.length,
    all.reduce((s, c) => s + c.lon, 0) / all.length,
  ];

  return (
    <MapContainer
      center={center}
      zoom={4}
      style={{ height: "100%", width: "100%", background: "#0a0f1d" }}
      scrollWheelZoom={false}
    >
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      />
      {tracks.map((t) => (
        <Polyline
          key={t.leg_id}
          positions={t.coords.map((c) => [c.lat, c.lon] as [number, number])}
          pathOptions={{ color: t.color, weight: 3, opacity: 0.85 }}
        >
          <Tooltip sticky>
            {t.mode} · {t.origin} → {t.destination}
          </Tooltip>
        </Polyline>
      ))}
      {tracks.map((t) => {
        const first = t.coords[0];
        const last = t.coords[t.coords.length - 1];
        return (
          <Fragment key={`pts-${t.leg_id}`}>
            <CircleMarker
              center={[first.lat, first.lon]}
              radius={5}
              pathOptions={{ color: t.color, fillColor: "#0a0f1d", fillOpacity: 1, weight: 2 }}
            >
              <Tooltip>{t.origin}</Tooltip>
            </CircleMarker>
            <CircleMarker
              center={[last.lat, last.lon]}
              radius={5}
              pathOptions={{ color: t.color, fillColor: t.color, fillOpacity: 1, weight: 2 }}
            >
              <Tooltip>{t.destination}</Tooltip>
            </CircleMarker>
          </Fragment>
        );
      })}
    </MapContainer>
  );
}
