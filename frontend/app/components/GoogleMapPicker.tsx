"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

export type PickedLocation = {
  lat: number;
  lon: number;
  source: "google_maps";
  label?: string;
};

declare global {
  interface Window {
    google?: any;
  }
}

const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;

export function GoogleMapPicker({
  open,
  onClose,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (location: PickedLocation) => void;
}) {
  const mapElement = useRef<HTMLDivElement>(null);
  const map = useRef<any>(null);
  const marker = useRef<any>(null);
  const [ready, setReady] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<PickedLocation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !apiKey) return;
    const initialize = () => {
      if (!mapElement.current || !window.google || map.current) return;
      map.current = new window.google.maps.Map(mapElement.current, {
        center: { lat: 23.685, lng: 90.3563 },
        zoom: 7,
        mapTypeControl: false,
        streetViewControl: false,
      });
      map.current.addListener("click", (event: any) => {
        const lat = event.latLng.lat();
        const lon = event.latLng.lng();
        marker.current ??= new window.google.maps.Marker({ map: map.current });
        marker.current.setPosition({ lat, lng: lon });
        setSelected({ lat, lon, source: "google_maps", label: "Google Maps pin" });
      });
      setReady(true);
    };
    if (window.google?.maps) {
      initialize();
      return;
    }
    const existing = document.querySelector<HTMLScriptElement>('script[data-google-maps="true"]');
    if (existing) {
      existing.addEventListener("load", initialize, { once: true });
      return () => existing.removeEventListener("load", initialize);
    }
    const script = document.createElement("script");
    script.dataset.googleMaps = "true";
    script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&v=weekly`;
    script.async = true;
    script.onload = initialize;
    script.onerror = () => setError("Google Maps could not load. Check your browser-restricted API key.");
    document.head.appendChild(script);
  }, [open]);

  useEffect(() => {
    if (!open) {
      map.current = null;
      marker.current = null;
      setReady(false);
      setSelected(null);
      setError(null);
    }
  }, [open]);

  function findPlace(event: FormEvent) {
    event.preventDefault();
    if (!query.trim() || !window.google || !map.current) return;
    new window.google.maps.Geocoder().geocode({ address: query }, (results: any[], status: string) => {
      if (status !== "OK" || !results?.[0]) {
        setError("Place not found. Search again or place a pin directly on the map.");
        return;
      }
      const result = results[0];
      const position = result.geometry.location;
      const lat = position.lat();
      const lon = position.lng();
      map.current.setCenter({ lat, lng: lon });
      map.current.setZoom(14);
      marker.current ??= new window.google.maps.Marker({ map: map.current });
      marker.current.setPosition({ lat, lng: lon });
      setSelected({ lat, lon, source: "google_maps", label: result.formatted_address });
      setError(null);
    });
  }

  if (!open) return null;
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="map-modal" role="dialog" aria-modal="true" aria-label="Choose farm location on Google Maps">
        <div className="modal-heading"><div><span className="section-label">GOOGLE MAPS</span><h2>Choose your farm location</h2></div><button className="icon-button" type="button" onClick={onClose}>×</button></div>
        {!apiKey ? <div className="notice danger"><strong>Google Maps key needed.</strong> Add `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` to `frontend/.env.local`, enable Maps JavaScript API and restrict the key to your frontend origin. Live location still works without a Maps key.</div> : <><form className="map-search" onSubmit={findPlace}><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search village, union or address" /><button type="submit" disabled={!ready}>Search</button></form><div ref={mapElement} className="map-canvas" />{error && <p className="map-error">{error}</p>}<p className="muted">Search a place, or tap the farm on the map to place a pin.</p>{selected && <div className="map-confirm"><span>{selected.label ?? `${selected.lat.toFixed(5)}, ${selected.lon.toFixed(5)}`}</span><button type="button" onClick={() => { onPick(selected); onClose(); }}>Use this farm location</button></div>}</>}
      </section>
    </div>
  );
}
