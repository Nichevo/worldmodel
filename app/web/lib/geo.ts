// Country shapes, fetched once and shared by every map on the page.

let shapes: Promise<GeoJSON.FeatureCollection> | null = null;

export function countryShapes(): Promise<GeoJSON.FeatureCollection> {
  if (!shapes) {
    shapes = fetch("/geo/countries.json").then((r) => {
      if (!r.ok) throw new Error(`country shapes: ${r.status}`);
      return r.json();
    });
    shapes.catch(() => { shapes = null; });
  }
  return shapes;
}
