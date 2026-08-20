import { useCallback, useEffect, useState } from "react";
import type { PreferenceCatalog } from "../types";
import { api } from "./api";
import {
  normalizePreferenceCatalog,
  readPreferenceCatalogCache,
  writePreferenceCatalogCache,
} from "./preferenceCatalog";

export function usePreferenceCatalog(locale: string) {
  const [catalog, setCatalog] = useState<PreferenceCatalog | null>(() => (
    readPreferenceCatalogCache(locale)?.catalog ?? null
  ));
  const [loading, setLoading] = useState(true);
  const [stale, setStale] = useState(Boolean(catalog));
  const [error, setError] = useState("");
  const [reloadIndex, setReloadIndex] = useState(0);

  const reload = useCallback(() => setReloadIndex((value) => value + 1), []);

  useEffect(() => {
    let active = true;
    const cached = readPreferenceCatalogCache(locale);
    if (cached) {
      setCatalog(cached.catalog);
      setStale(true);
    } else {
      setCatalog(null);
      setStale(false);
    }
    setLoading(true);
    setError("");
    api.getPreferenceCatalog(locale, cached)
      .then((result) => {
        if (!active) return;
        const normalized = normalizePreferenceCatalog(result.catalog, locale);
        setCatalog(normalized);
        setStale(false);
        writePreferenceCatalogCache(locale, { etag: result.etag, catalog: normalized });
      })
      .catch((cause) => {
        if (!active) return;
        setError(cause instanceof Error ? cause.message : "PREFERENCE_CATALOG_NOT_AVAILABLE");
        setStale(Boolean(cached));
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [locale, reloadIndex]);

  return { catalog, loading, stale, error, reload };
}
